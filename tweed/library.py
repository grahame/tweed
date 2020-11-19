import os
import json
import requests
import functools
import urllib.parse
import re
from collections import namedtuple, Counter
from lxml import etree
from hashlib import sha256

Book = namedtuple("Book", ("ddc", "author", "title", "isbn"))


def one(l):
    assert len(l) == 1
    return l[0]


ddc_re = re.compile(r"^[0-9]")


def is_ddc(v):
    return ddc_re.match(str(v)) is not None


class OCLC:
    def __init__(self):
        self.session = requests.Session()
        self.book_holdings = Counter()

    def recursive_lookup(self, **kwargs):
        """
        recursive lookup; may return more than one <work/> document
        """

        def get(url):
            print("OCLC lookup: {}".format(url))
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
            return list(
                functools.reduce(
                    lambda a, b: a + b,
                    (self.recursive_lookup(wi=wi) for wi in x("//c:work/@wi")),
                )
            )
        elif responses[0] == "101":
            raise Exception("invalid data: {}".format(kwargs))
        elif responses[0] == "102":
            return None
        else:
            raise Exception(responses[0])

    def lookup(self, isbn):
        results = self.recursive_lookup(isbn=isbn)
        if results is None:
            return

        def work_to_book(fname):
            et = etree.parse(fname)
            x = lambda q: et.xpath(q, namespaces={"c": "http://classify.oclc.org"})
            work = one(x("/c:classify/c:work"))

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
            return holdings, Book(ddc, work.get("author"), work.get("title"), isbn)

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
        )

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
            )


class Library:
    def __init__(self):
        self.meta = LibraryMetadata()
        arrangement = self.arrange()
        for book in arrangement:
            print(
                "☐ {:14} {:16} {:10}  {:18}  {}".format(
                    (book.ddc or "")[:14],
                    (book.isbn or "")[:16],
                    self.meta.oclc.book_holdings.get(book.isbn or "", ""),
                    book.author.split("|", 1)[0][:16],
                    book.title[:60],
                )
            )

    def arrange(self):
        fiction = []
        nonfiction = []
        for book in self.meta:
            if not book.ddc or book.ddc.startswith("8"):
                fiction.append(book)
            else:
                nonfiction.append(book)

        def fiction_key(book):
            return (book.author.lower(), book.title.lower())

        def nonfiction_key(book):
            return (book.ddc, book.author.lower(), book.title.lower())

        fiction.sort(key=fiction_key)
        nonfiction.sort(key=nonfiction_key)
        return nonfiction + fiction
