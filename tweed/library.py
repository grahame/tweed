import os
import json
import datetime
import requests
import functools
import urllib.parse
import re
import sys
from collections import namedtuple, Counter
from lxml import etree
from hashlib import sha256

Book = namedtuple("Book", ("ddc", "author", "title", "isbn", "date"))


def one(l):
    assert len(l) == 1
    return l[0]


ddc_re = re.compile(r"^[0-9]")


def is_ddc(v):
    return ddc_re.match(str(v)) is not None


class OCLC:
    ISBN_WID_OVERRIDES = {
        "9780232525274": "54781379",
        "9780241339725": "1031083726",
        "9781782275909": "1119766390",
    }
    ISBN_DISABLE = [
        "9780648228202",
        "9788129115546",
        "9780721412634",
        "9780938819806",
        "9780486442136",
        "9780664223083",
        "9780664223090",
    ]

    def __init__(self):
        self.session = requests.Session()
        self.book_holdings = Counter()

    def recursive_lookup(self, **kwargs):
        """
        recursive lookup; may return more than one <work/> document
        """

        def get(url):
            print("OCLC lookup: {}".format(url), file=sys.stderr)
            response = self.session.get(
                "http://classify.oclc.org/classify2/Classify", params=params
            )
            assert response.status_code == 200
            return response.content

        params = list(kwargs.items())
        params.append(("summary", False))
        params.sort()
        url = "http://classify.oclc.org/classify2/Classify?" + urllib.parse.urlencode(
            params
        )
        url_hash = sha256(url.encode("utf8")).hexdigest()
        cache_fname = os.path.join("cache", "oclc_lookup_{}.xml".format(url_hash))
        tmp_fname = cache_fname + ".tmp"
        if not os.access(cache_fname, os.R_OK):
            with open(tmp_fname, "wb") as fd:
                fd.write(get(url))
            os.rename(tmp_fname, cache_fname)

        et = etree.parse(cache_fname)
        x = lambda q: et.xpath(q, namespaces={"c": "http://classify.oclc.org"})
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

        def work_to_book(fname):
            et = etree.parse(fname)
            x = lambda q: et.xpath(q, namespaces={"c": "http://classify.oclc.org"})
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
            # rank by overall holdings for this work, not just the particular classification
            return int(work.get("holdings")), Book(
                ddc,
                get_author(),
                work.get("title"),
                isbn,
                None,
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
            )

        books = [
            (h, b)
            for (h, b) in (work_to_book(fname) for fname in results)
            if h is not None
        ]
        if not books:
            return None
        books.sort(reverse=True, key=lambda x: x[0])
        self.book_holdings[isbn] += sum(t[0] for t in books)
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
            LibraryThing.get_author(book),
            LibraryThing.get_title(book),
            LibraryThing.get_isbn(book),
            LibraryThing.get_date(book),
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
    responsible for providing a merged view of LibraryThing (authoritative for the books I own)
    and OCLC (often much better metadata)
    """

    def __init__(self):
        self.lt = LibraryThing()
        self.oclc = OCLC()

    def lookup_lt_in_oclc(self, book):
        if not book.isbn:
            return None
        return self.oclc.lookup(isbn=book.isbn)

    def __iter__(self):
        def a_first(a, b):
            if a is not None and len(a) > 0:
                return a
            return b

        for lt_book in self.lt:
            oclc_book = self.lookup_lt_in_oclc(lt_book)
            if oclc_book is None:
                yield lt_book
                continue
            assert oclc_book.isbn == lt_book.isbn
            best_attr = lambda x: a_first(getattr(oclc_book, x), getattr(lt_book, x))
            yield Book(
                best_attr("ddc"),
                best_attr("author"),
                best_attr("title"),
                best_attr("isbn"),
                best_attr("date"),
            )


class Library:
    def __init__(self):
        self.meta = LibraryMetadata()
        self.arrangement = self.arrange()
        self.write_index_txt()
        self.write_json()

    def write_json(self):
        obj = {"books": []}
        seen = set()
        for book in self.arrangement:
            book_obj = (
                ("ddc", book.ddc),
                ("isbn", book.isbn),
                ("author", book.author),
                ("date", str(book.date)),
                ("title", book.title),
            )
            if book_obj in seen:
                continue
            seen.add(book_obj)
            obj["books"].append(dict(book_obj))
        with open("frontend/src/books.json", "w") as fd:
            json.dump(obj, fd)

    def write_index_txt(self):
        for book in self.arrangement:
            print(
                "{:14} {:16}  {:28}  {:4} {}".format(
                    (book.ddc or "")[:14],
                    (book.isbn or "")[:16],
                    book.author[:26],
                    str(book.date)[:4],
                    book.title[:60],
                )
            )

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
        return books
