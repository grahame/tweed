import json
import datetime
import csv
import sys
from collections import Counter


def main():
    with open("data/librarything_grahame.json") as fd:
        data = json.load(fd)

    date_books = Counter()
    for book_id, book in data.items():
        dt = datetime.datetime.strptime(book["entrydate"], "%Y-%m-%d").date()
        date_books[dt] += 1

    w = csv.writer(sys.stdout)
    w.writerow(["date", "books"])
    total = 0
    for date in sorted(date_books.keys()):
        n = date_books[date]
        total += n
        w.writerow([date, total])


if __name__ == "__main__":
    main()