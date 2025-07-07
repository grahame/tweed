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

isbnfilecache = {}
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
    if "@isbnfile" in query:
        isbnf = query["@isbnfile"]
        if isbnf not in isbnfilecache:
            with open(isbnf, "r") as fd:
                isbnfilecache[isbnf] = set(line.strip() for line in fd)
        match &= book.isbn in isbnfilecache[isbnf]
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
        with open('data/isbn_overrides.json') as fd:
            self.isbn_overrides = json.load(fd)

    def __iter__(self):
        keys = ["ddc", "author", "title", "isbn", "date", "books_id"]
        for lt_book in self.lt:
            attrs = {k: getattr(lt_book, k) for k in keys}
            attrs.update(self.isbn_overrides.get(lt_book.isbn, {}))
            book = Book(**attrs)
            yield book
        with open("data/isbn_overrides.json", "w") as fd:
            json.dump(self.isbn_overrides, fd, indent=4)


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
                return "{:4} {:7} {:14} {:28}  {}".format(
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

        # place everything else linearly across available shelf space, starting at the first shelf mentioned
        current_shelf = shelves[0]
        for book in books:
            # check if we are at the start of another shelf
            for shelf in shelves:
                if query_matches(shelf["first_book"], book) and not get_override(book):
                    current_shelf = shelf
                    break
            # skip overridden books, already placed
            if get_override(book):
                continue
            # default to the current shelf
            print(current_shelf, book)
            assert(current_shelf != None)
            place_book(current_shelf, book)
        return placed

    def arrange(self):
        books = list(self.meta)

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
            if not matched:
                raise Exception("no match for book: {}".format(book))

        indexes = defaultdict(lambda: 1)
        placed = []
        overrides = arrangement["overrides"]
        for zone, subbooks in zone_books.items():
            sort_method = zones[zone]['sort']
            if sort_method == 'ddc':
                subbooks.sort(
                    key=lambda book: (
                        book.ddc is None,
                        book.ddc,
                        book.author.lower(),
                        book.title.lower(),
                    )
                )
            elif sort_method == 'author':
                subbooks.sort(
                    key=lambda book: (
                        book.author.lower(),
                        book.title.lower(),
                    )
                )
            else:
                raise Exception("unknown sort method: {}".format(sort_method))
            shelves = zones[zone]["shelves"]
            print("arranging zone {} with {} shelves and {} books".format(zone, len(shelves), len(subbooks)))
            placed += self.subarrange(indexes, subbooks, shelves, overrides)

        sort_re = re.compile(r"^([A-Z]+)(\d+)\.(\d+)$")

        def sort_key(book):
            match = sort_re.match(book.location)
            assert match
            return (match.group(1), int(match.group(2)), int(match.group(3)))

        placed.sort(key=sort_key)
        return placed
