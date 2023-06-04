import os
import json
import datetime
import requests
import functools
import html
from itertools import tee
import urllib.parse
import re
import sys
from collections import namedtuple, Counter, defaultdict
from lxml import etree
from hashlib import sha256

Book = namedtuple("Book", ("ddc", "author", "title", "isbn", "date", "books_id"))
BookPlacement = namedtuple("BookPlacement", ("book", "location"))

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


def query_matches(query, book):
    match = True
    if "ddc" in query:
        match &= re.match(query["ddc"], book.ddc or "") is not None
    if "isbn" in query:
        match &= book.isbn == query["isbn"]
    if "title" in query:
        match &= match_string(query["title"], book.title)
    if "author" in query:
        match &= match_string(query["author"], book.author)
    return match


def oclc_scrape(isbn):
    url = 'http://classify.oclc.org/classify2/ClassifyDemo?search-standnum-txt={}&startRec=0'.format(isbn)
    cache_fname = os.path.join("cache", "oclc_scrape_{}.html".format(isbn))
    tmp_fname = cache_fname + ".tmp"
    if not os.access(cache_fname, os.R_OK):
        r = requests.get(url)
        assert(r.status_code == 200)
        with open(tmp_fname, "wb") as f:
            f.write(r.content)
        os.rename(tmp_fname, cache_fname)

    et = etree.parse(cache_fname, parser=etree.HTMLParser())
    codes = et.xpath("//td/text()[normalize-space(.)='Most Frequent']/../following-sibling::td[1]/text()")
    codes = [t for t in codes if ddc_re.match(t)]
    if len(codes) == 0:
        return None
    return codes[0]


class OCLC:
    ISBN_WID_OVERRIDES = {
        "9780232525274": "54781379",
        "9780241339725": "1031083726",
        "9781782275909": "1119766390",
        "9780300139495": "185739559",
        "9780334010999": "24322",
        "9780198261681": "16538526",
    }
    ISBN_DISABLE = [
        "9781612182377",
        "9780281045556",
        "9780664218300",
        "9780553401653",
        "9780648228202",
        "9788129115546",
        "9780721412634",
        "9780938819806",
        "9780486442136",
        "9780664223083",
        "9780664223090",
        "9780664223083",
        "9780664223090",
        "9780310521938",
        "9780310522003",
        "9780415267670",
        "9780140444216",
        "9781473647671",
        "9780140441147",
        "9781565484467",
        "9780199537822",
        "9780199540631",
        "9780486836089",
    ]

    def __init__(self):
        self.session = requests.Session()

    def recursive_lookup(self, **kwargs):
        """
        recursive lookup; may return more than one <work/> document
        """

        params = list(kwargs.items())
        params.append(("summary", False))
        params.sort()
        url = "http://classify.oclc.org/classify2/Classify?" + urllib.parse.urlencode(
            params
        )
        url_hash = sha256(url.encode("utf8")).hexdigest()
        cache_fname = os.path.join("cache", "oclc_lookup_{}.xml".format(url_hash))
        if not os.access(cache_fname, os.R_OK):
            # they nuked free access to the API; to avoid a massive re-sort, we don't
            # want to break previously cached results. However, we can relatively safely
            # scrape for those books we had no previous results for.
            return "SCRAPE_HACK"

        et = etree.parse(cache_fname)
        def x(q):
            return et.xpath(q, namespaces={"c": "http://classify.oclc.org"})
        responses = x("/c:classify/c:response/@code")
        assert len(responses) == 1

        if responses[0] == "2":
            return [cache_fname]
        elif responses[0] == "4":
            wis = x("//c:work/@wi")
            isbn = kwargs.get("isbn")
            if isbn in self.ISBN_WID_OVERRIDES:
                wis = [self.ISBN_WID_OVERRIDES[isbn]]
            return list(
                functools.reduce(
                    lambda a, b: a + b, (self.recursive_lookup(wi=wi) for wi in wis)
                )
            )
        elif responses[0] == "101":
            raise Exception("invalid data: {}".format(kwargs))
        elif responses[0] == "102":
            return None
        else:
            raise Exception(responses[0])

    def lookup(self, isbn):
        if isbn in self.ISBN_DISABLE:
            return
        results = self.recursive_lookup(isbn=isbn)
        if results is None:
            return
        if results == 'SCRAPE_HACK':
            ddc = oclc_scrape(isbn)
            if ddc is None:
                return
            return Book(isbn=isbn, ddc=ddc, author=None, title=None, date=None, books_id=None)

        def work_to_book(fname):
            et = etree.parse(fname)

            def x(q):
                return et.xpath(q, namespaces={"c": "http://classify.oclc.org"})
            work = one(x("/c:classify/c:work"))

            def get_author():
                author = work.get("author")
                if author is None:
                    return
                return author.split("|", 1)[0].strip()

            def get_ddc(title, attr):
                ddcs = x("/c:classify/c:recommendations/c:ddc/c:{}".format(title))
                if len(ddcs) == 0:
                    return None, None
                return int(ddcs[0].get("holdings", 0)), ddcs[0].get(attr)

            candidate_ddcs = [
                (h, d)
                for (h, d) in [
                    get_ddc("mostPopular", "nsfa"),
                    get_ddc("mostPopular", "sfa"),
                    get_ddc("mostRecent", "nsfa"),
                    get_ddc("mostRecent", "sfa"),
                ]
                if is_ddc(d)
            ]
            if not candidate_ddcs:
                return None, None
            holdings, ddc = candidate_ddcs[0]

            # rank by overall holdings for this work, not just the particular
            # classification
            return int(work.get("holdings")), Book(
                ddc, he(get_author()), he(work.get("title")), isbn, None, None
            )

        def fill_blanks(a, b):
            if not a:
                return b
            return a

        def merge_book(a, b):
            return Book(
                fill_blanks(a.ddc, b.ddc),
                fill_blanks(a.author, b.author),
                fill_blanks(a.title, b.title),
                fill_blanks(a.isbn, b.isbn),
                fill_blanks(a.date, b.date),
                fill_blanks(a.books_id, b.books_id),
            )

        books = [
            (h, b)
            for (h, b) in (work_to_book(fname) for fname in results)
            if h is not None
        ]
        if not books:
            return None
        books.sort(reverse=True, key=lambda x: x[0])
        books = [t[1] for t in books]
        reduced = functools.reduce(merge_book, books)
        return reduced


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
    responsible for providing a merged view of LibraryThing
    (authoritative for the books that I own) and OCLC (often much better metadata)
    """

    def __init__(self):
        self.lt = LibraryThing()
        self.oclc = OCLC()

    def lookup_lt_in_oclc(self, book):
        if not book.isbn:
            return None
        return self.oclc.lookup(isbn=book.isbn)

    def __iter__(self):

        for lt_book in self.lt:
            oclc_book = self.lookup_lt_in_oclc(lt_book)
            if oclc_book is None:
                yield lt_book
                continue
            assert oclc_book.isbn == lt_book.isbn
            def best_attr(x):
                a = getattr(oclc_book, x)
                b = getattr(lt_book, x)
                if a is not None and len(a) > 0:
                    return a
                return b
            yield Book(
                best_attr("ddc"),
                best_attr("author"),
                best_attr("title"),
                best_attr("isbn"),
                best_attr("date"),
                best_attr("books_id"),
            )


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
            def insert(book):
                print("insert:", book)

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
                        r"^([A-Z]+)(\d+)\.(\d+)", book["loc"]
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
                return "{:4} {:14} {:28}  {}".format(
                    book["loc"],
                    (book["isbn"] or "")[:14],
                    book["author"][:26],
                    book["title"][:40],
                )

            def book_msg(s, book):
                if not book:
                    return
                print("{:>1} {}".format(s, describe(book)))

            for (tpl, op, book_before, book, book_after) in instructions:
                book_msg("", book_before)
                book_msg(op, book)
                book_msg("", book_after)
                print()

        BOOKS_JSON = "frontend/src/books.json"
        with open(BOOKS_JSON) as fd:
            old_state = json.load(fd)
        new_state = get_state()

        # make a report for the librarian
        report(old_state["books"], new_state["books"])

        with open("frontend/src/books.json", "w") as fd:
            json.dump(new_state, fd)

    def write_index_txt(self):
        with open("library.txt.new", "w") as fd:
            for bp in self.arrangement:
                print(
                    "{:4} {:14} {:16}  {:28}  {:4} {}".format(
                        bp.location,
                        (bp.book.ddc or "")[:14],
                        (bp.book.isbn or "")[:16],
                        bp.book.author[:26],
                        str(bp.book.date)[:4],
                        bp.book.title[:60],
                    ),
                    file=fd,
                )
        os.rename("library.txt.new", "library.txt")

    @staticmethod
    def subarrange(indexes, books, shelves, overrides):
        def format_loc(shelf, index):
            return "{}{}.{:>02}".format(shelf["bookshelf"], shelf["shelf"], index)

        placed = []

        def get_override(book):
            for override in overrides:
                if query_matches(override, book):
                    return override

        def place_book(placed_on, book):
            index_key = (placed_on["bookshelf"], placed_on["shelf"])
            index = indexes[index_key]
            indexes[index_key] += 1
            placed.append(BookPlacement(book, format_loc(placed_on, index)))

        # overriden books go to the start of their shelf
        for book in books:
            placed_on = get_override(book)
            if placed_on is not None:
                place_book(placed_on, book)

        # place everything else linearly across available shelf space
        current_shelf = None
        for book in books:
            print(current_shelf, book.ddc, book.title)
            # check if we are at the start of another shelf
            for shelf in shelves:
                if query_matches(shelf["first_book"], book) and not get_override(book):
                    current_shelf = shelf
                    break
            # skip overridden books, already placed
            if get_override(book):
                continue
            # default to the current shelf
            place_book(current_shelf, book)
        return placed

    def arrange(self):
        books = list(self.meta)
        books.sort(
            key=lambda book: (
                book.ddc is None,
                book.ddc,
                book.author.lower(),
                book.title.lower(),
            )
        )

        # allocate to shelves
        with open("data/arrangement.json") as fd:
            arrangement = json.load(fd)

        # routing
        zones = arrangement["zones"]
        zone_books = {zone: [] for zone in zones}
        zone_matches = [(z, zones[z]["matches"]) for z in zones]

        for book in books:
            matched = False
            for zone, zm in zone_matches:
                if any(query_matches(t, book) for t in zm):
                    matched = True
                    zone_books[zone].append(book)
                    break
            assert matched

        indexes = defaultdict(lambda: 1)
        placed = []
        overrides = arrangement["overrides"]
        for zone, subbooks in zone_books.items():
            shelves = zones[zone]["shelves"]
            placed += self.subarrange(indexes, subbooks, shelves, overrides)

        sort_re = re.compile(r"^([A-Z]+)(\d+)\.(\d+)$")

        def sort_key(book):
            match = sort_re.match(book.location)
            assert match
            return (match.group(1), int(match.group(2)), int(match.group(3)))

        placed.sort(key=sort_key)
        return placed
