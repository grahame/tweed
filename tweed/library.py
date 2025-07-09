import os
import json
import datetime
import html
from itertools import tee
import re
import sys
import isbnlib
from collections import namedtuple, defaultdict, Counter

Book = namedtuple("Book", ("ddc", "author", "title", "isbn", "date", "books_id"))
BookPlacement = namedtuple("BookPlacement", ("book", "location", "zone"))


# https://docs.python.org/3/library/itertools.html
def pairwise(iterable):
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def he(s):
    if s is None:
        return
    return html.unescape(s)


def one(elems):
    assert len(elems) == 1
    return elems[0]


ddc_re = re.compile(r"^[0-9]")


def is_ddc(v):
    return ddc_re.match(str(v)) is not None


def match_string(query, s):
    if query.startswith("r:"):
        return re.match(query[2:], s) is not None
    return query == s


class ISBNFile:
    def __init__(self, fname):
        self.fname = fname
        self.entries = Counter()
        with open(fname) as fd:
            for line in (t.strip() for t in fd):
                if not line:
                    continue
                isbn = isbnlib.to_isbn13(line)
                if isbn == "9781473232297":
                    print("YES")
                if not isbn:
                    print("{}: invalid ISBN in file {}".format(fname, line))
                    continue
                self.entries[isbn] = 0

    def check(self, isbn):
        if isbn is None:
            return False
        isbn = isbnlib.to_isbn13(isbn)
        if not isbn:
            return False
        if isbn not in self.entries:
            return False
        self.entries[isbn] += 1
        return True

    def report(self):
        for e, c in self.entries.items():
            if c == 0:
                print("{}: ISBN not matched - {}".format(self.fname, e))


class ISBNFileAccess:
    def __init__(self):
        self.files = {}

    def load(self, fname):
        if fname in self.files:
            return self.files[fname]
        self.files[fname] = ISBNFile(fname)
        return self.files[fname]

    def report(self):
        for file in self.files.values():
            file.report()


def query_matches(isbnfa, query, book):
    match = True
    if "ddc" in query:
        match &= re.match(query["ddc"], book.ddc or "") is not None
    if "isbn" in query:
        match &= book.isbn == query["isbn"]
    if "title" in query:
        match &= match_string(query["title"], book.title)
    if "author" in query:
        match &= match_string(query["author"], book.author)
    if "@isbnfile" in query:
        match &= isbnfa.load(query["@isbnfile"]).check(book.isbn)
    return match


class LibraryThing:
    def __init__(self, fname="data/librarything_grahame.json"):
        with open(fname, "r") as fd:
            self.data = json.load(fd)

    def __iter__(self):
        return (LibraryThing.get_book(t) for t in self.data.values())

    @staticmethod
    def get_book(book):
        return Book(
            LibraryThing.get_ddc(book),
            he(LibraryThing.get_author(book)),
            he(LibraryThing.get_title(book)),
            LibraryThing.get_isbn(book),
            LibraryThing.get_date(book),
            LibraryThing.get_books_id(book),
        )

    @staticmethod
    def get_date(book):
        if "date" not in book:
            return None
        date = book["date"]
        if date == "?" or date == "no date":
            return
        try:
            return datetime.datetime.strptime(date, "%Y").date()
        except ValueError:
            print("failed to parse: {}".format(date), file=sys.stderr)

    @staticmethod
    def get_ddc(book):
        if "ddc" not in book:
            return None
        return book["ddc"]["code"][0]

    @staticmethod
    def get_books_id(book):
        return int(book["books_id"])

    @staticmethod
    def get_isbn(book):
        isbn = book.get("isbn")
        if type(isbn) is dict and "2" in isbn:
            return isbn["2"]
        return book.get("originalisbn")

    @staticmethod
    def get_title(book):
        return book["title"]

    @staticmethod
    def get_author(book):
        author = book["authors"][0]
        if type(author) is not dict:
            author = ""
        else:
            author = author["lf"]
        return author


class LibraryMetadata:
    """
    responsible for providing a merged view of LibraryThing with overriden metadata
    """

    def __init__(self):
        self.lt = LibraryThing()
        with open("data/isbn_overrides.json") as fd:
            self.isbn_overrides = json.load(fd)

    def __iter__(self):
        keys = ["ddc", "author", "title", "isbn", "date", "books_id"]
        for lt_book in self.lt:
            attrs = {k: getattr(lt_book, k) for k in keys}
            attrs.update(self.isbn_overrides.get(lt_book.isbn, {}))
            book = Book(**attrs)
            yield book
        with open("data/isbn_overrides.json", "w") as fd:
            json.dump(self.isbn_overrides, fd, indent=4, ensure_ascii=False)


class Library:
    def __init__(self):
        self.meta = LibraryMetadata()
        self.arrangement = self.arrange()
        self.write_index_txt()
        self.write_json()

    def write_json(self):
        def get_state():
            obj = {"books": []}
            seen = set()
            for bp in self.arrangement:
                book_obj = (
                    ("loc", bp.location),
                    ("zone", bp.zone),
                    ("ddc", bp.book.ddc),
                    ("isbn", bp.book.isbn),
                    ("author", bp.book.author),
                    ("date", str(bp.book.date)),
                    ("title", bp.book.title),
                    ("books_id", bp.book.books_id),
                )
                if book_obj in seen:
                    continue
                seen.add(book_obj)
                obj["books"].append(dict(book_obj))
            return obj

        def report(old, new):
            old_books_id = set(t["books_id"] for t in old)
            new_books_id = set(t["books_id"] for t in new)
            row_index = dict((t["books_id"], idx) for (idx, t) in enumerate(new))

            # paranoia: validate core assumption
            assert len(old_books_id) == len(old)
            assert len(new_books_id) == len(new)

            def make_instructions(op, books_ids):
                r = []
                for book_id in books_ids:
                    if book_id not in row_index:
                        continue
                    book_index = row_index[book_id]
                    book = new[book_index]
                    book_before = book_after = None
                    if book_index > 0:
                        book_before = new[book_index - 1]
                    if book_index < len(new) - 1:
                        book_after = new[book_index + 1]
                    case, shelf, offset = re.match(
                        r"^([A-Z\-]+)(\d+)\.(\d+)", book["loc"]
                    ).groups()
                    r.append(
                        (
                            (case, int(shelf), int(offset)),
                            op,
                            book_before,
                            book,
                            book_after,
                        )
                    )
                return r

            instructions = []
            added_books_id = new_books_id - old_books_id
            instructions += make_instructions("+", added_books_id)
            removed_books_id = old_books_id - new_books_id
            instructions += make_instructions("-", removed_books_id)
            instructions.sort()

            def describe(book):
                return "{:6} {:10} {:7} {:14} {:28}  {}".format(
                    book["zone"],
                    book["loc"],
                    (book["ddc"] or "")[:6],
                    (book["isbn"] or "")[:14],
                    book["author"][:26],
                    book["title"][:40],
                )

            def book_msg(s, book):
                if not book:
                    return
                print("{:>1} {}".format(s, describe(book)))

            for tpl, op, book_before, book, book_after in instructions:
                book_msg("", book_before)
                book_msg(op, book)
                book_msg("", book_after)
                print()

        OLD_BOOKS_JSON = "data/books-as-placed.json"
        BOOKS_JSON = "frontend/src/books.json"
        with open(OLD_BOOKS_JSON) as fd:
            old_state = json.load(fd)
        new_state = get_state()

        # make a report for the librarian
        report(old_state["books"], new_state["books"])

        with open(BOOKS_JSON, "w") as fd:
            json.dump(new_state, fd, ensure_ascii=False)

    def write_index_txt(self):
        isbn_count = Counter()
        with open("library.txt.new", "w") as fd:
            for bp in self.arrangement:
                warnings = []
                if bp.book.isbn:
                    isbn_count[bp.book.isbn] += 1
                    if isbn_count[bp.book.isbn] > 1:
                        warnings.append("duplicate")
                if not bp.book.ddc:
                    warnings.append("no-dewey")
                warnings = ", ".join(warnings)
                if warnings:
                    warnings = " !! [" + warnings + "]"
                print(
                    "{:4} {:14} {:16}  {:28}  {:4} {}{}".format(
                        bp.location,
                        (bp.book.ddc or "")[:14],
                        (bp.book.isbn or "")[:16],
                        bp.book.author[:26],
                        str(bp.book.date)[:4],
                        bp.book.title[:60],
                        warnings,
                    ),
                    file=fd,
                )
        os.rename("library.txt.new", "library.txt")

    @staticmethod
    def subarrange(isbnfa, zone, indexes, books, shelves, overrides):
        def format_loc(shelf, index):
            return "{}{}.{:>02}".format(shelf["bookshelf"], shelf["shelf"], index)

        placed = []

        def get_override(book):
            for override in overrides:
                if query_matches(isbnfa, override, book):
                    return override

        def place_book(zone, placed_on, book):
            index_key = (placed_on["bookshelf"], placed_on["shelf"])
            index = indexes[index_key]
            indexes[index_key] += 1
            placed.append(BookPlacement(book, format_loc(placed_on, index), zone))

        # overriden books go to the start of their shelf
        for book in books:
            placed_on = get_override(book)
            if placed_on is not None:
                place_book(zone, placed_on, book)

        # place everything else linearly across available shelf space, starting at the first shelf mentioned
        current_shelf = shelves[0]
        for book in books:
            # check if we are at the start of another shelf
            for shelf in shelves:
                if query_matches(
                    isbnfa, shelf["first_book"], book
                ) and not get_override(book):
                    current_shelf = shelf
                    break
            # skip overridden books, already placed
            if get_override(book):
                continue
            # default to the current shelf
            assert current_shelf is not None
            place_book(zone, current_shelf, book)
        return placed

    def rewrite(self, books, arrangement):
        nb = []
        for book in books:
            up = book._asdict()
            # apply replacements
            for attr, match_re, subst_re in arrangement["rewrite"]:
                up[attr] = re.sub(match_re, subst_re, up.get(attr, ""))
            nb.append(Book(**up))
        return nb

    def arrange(self):
        isbnfa = ISBNFileAccess()

        # allocate to shelves
        with open("data/arrangement.json") as fd:
            arrangement = json.load(fd)
        books = self.rewrite(list(self.meta), arrangement)
        # routing
        zones = arrangement["zones"]
        zone_books = {zone: [] for zone in zones}
        zone_matches = [(z, zones[z]["matches"]) for z in zones]

        for book in books:
            matched = False
            for zone, zm in zone_matches:
                if any(query_matches(isbnfa, t, book) for t in zm):
                    matched = True
                    zone_books[zone].append(book)
                    break
            if not matched:
                raise Exception("no match for book: {}".format(book))

        indexes = defaultdict(lambda: 1)
        placed = []
        overrides = arrangement["overrides"]

        # we want to keep sort-keys stable, unless we want to reindex manually, so that
        # changes in upstream datasets don't randomly move our books around
        with open("data/sort_keys.json") as fd:
            sort_keys = json.load(fd)

        for book in books:
            cache_key = str(book.books_id)
            if cache_key in sort_keys and sort_keys[cache_key]["_rev"] == 1:
                continue
            print("reindexing book {}".format(book.books_id))
            sort_keys[cache_key] = {
                "_rev": 1,
                "ddc": [
                    book.ddc is None,
                    book.ddc,
                    book.author.lower(),
                    book.title.lower(),
                ],
                "author": [book.author.lower(), book.title.lower()],
            }

        with open("data/sort_keys.json", "w") as fd:
            # prune out anything with missing DDC, as that's a basic data entry problem
            # we don't want hanging around forever
            json.dump(
                {k: v for k, v in sort_keys.items() if not v["ddc"][0]},
                fd,
                indent=4,
                ensure_ascii=False,
            )

        for zone, subbooks in zone_books.items():
            sort_method = zones[zone]["sort"]
            subbooks.sort(key=lambda book: sort_keys[str(book.books_id)][sort_method])
            shelves = zones[zone]["shelves"]
            print(
                "zone {} has {} shelves and {} books".format(
                    zone, len(shelves), len(subbooks)
                )
            )
            placed += self.subarrange(
                isbnfa, zones[zone]["code"], indexes, subbooks, shelves, overrides
            )

        sort_re = re.compile(r"^([A-Z\-]+)(\d+)\.(\d+)$")

        def sort_key(book):
            match = sort_re.match(book.location)
            assert match
            return (match.group(1), int(match.group(2)), int(match.group(3)))

        placed.sort(key=sort_key)

        isbnfa.report()

        return placed
