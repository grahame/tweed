import React, { useState, useRef, useEffect } from "react";
import "./App.css";
import { Table, Form, Row, Col, Input, Button, ButtonGroup } from "reactstrap";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBarsStaggered, faBook } from "@fortawesome/free-solid-svg-icons";
import Books from "./books.json";

function useInput(): [string, JSX.Element] {
    const [value, setValue] = useState<string>("");
    const inputReference = useRef<HTMLInputElement>(null);

    useEffect(() => {
        inputReference.current?.focus();
    }, []);

    const input = (
        <Input
            innerRef={inputReference}
            className="bg-dark text-light"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            type="text"
        />
    );
    return [value, input];
}

interface BookProp {
    books: typeof Books.books;
    realMatches: Set<number>;
}

function BookTable(props: React.PropsWithChildren<BookProp>) {
    const { books, realMatches } = props;
    const tableRows = () => {
        return books.map((book) => {
            const match = realMatches.has(book.books_id);
            return (
                <tr key={book.books_id} className={match ? "matchRow" : ""}>
                    <td>{book.loc}</td>
                    <td>{book.ddc}</td>
                    <td>{book.author}</td>
                    <td>{book.title}</td>
                    <td>{book.isbn}</td>
                    <td>{book.date}</td>
                </tr>
            );
        });
    };
    return (
        <Table dark striped>
            <thead>
                <tr>
                    <th>#</th>
                    <th>DDC</th>
                    <th>Author</th>
                    <th>Title</th>
                    <th>ISBN</th>
                    <th>Date</th>
                </tr>
            </thead>
            <tbody>{tableRows()}</tbody>
        </Table>
    );
}

function App() {
    const [searchString, searchStringInput] = useInput();
    const [bookRows, setBookRows] = useState<typeof Books.books>(Books.books);
    const [realMatches, setRealMatches] = useState<Set<number>>(new Set());
    const [fuzzy, setFuzzy] = useState<boolean>(false);
    const [error, setError] = useState<string | null>();

    React.useEffect(() => {
        const filterBook = (book: typeof Books.books[0], re: RegExp) => {
            return re.test(book.author) || re.test(book.title);
        };
        const safeRe = () => {
            return new RegExp("^.*$", "i");
        };
        const makeRe = (s: string) => {
            try {
                const re = new RegExp(s, "i");
                setError(null);
                return re;
            } catch (e: any) {
                setError(e.toString());
                return safeRe();
            }
        };
        const userRe = () => {
            return makeRe(searchString.toString());
        };
        const reFilter = () => {
            var re = userRe();
            // build a list of matching books
            var i = 0;
            const matchingIndeces = new Set<number>();
            for (const book of Books.books) {
                if (filterBook(book, re)) {
                    matchingIndeces.add(i);
                }
                ++i;
            }
            return matchingIndeces;
        };

        const realMatches = new Set<number>();
        const matchingBooks: typeof Books.books = [];
        const matchingIndeces = reFilter();
        var i = 0;
        for (const book of Books.books) {
            var matched = false;
            if (matchingIndeces.has(i)) {
                matchingBooks.push(book);
                if (fuzzy) {
                    realMatches.add(book.books_id);
                }
                matched = true;
            }
            if (!matched && fuzzy) {
                for (var j = 1; j < 3; ++j) {
                    if (matchingIndeces.has(i + j) || matchingIndeces.has(i - j)) {
                        matchingBooks.push(book);
                        break;
                    }
                }
            }
            ++i;
        }
        setRealMatches(realMatches);
        setBookRows(matchingBooks);
    }, [searchString, fuzzy]);

    return (
        <div>
            <Form>
                <Row className="bg-dark">
                    <Col xs={{ size: 8, offset: 1 }}>{searchStringInput}</Col>
                    <Col xs={{ size: 2 }}>
                        <ButtonGroup>
                            <Button active={fuzzy} onClick={() => setFuzzy(!fuzzy)}>
                                <FontAwesomeIcon icon={faBarsStaggered} />
                            </Button>
                            <Button onClick={() => false}>
                                <FontAwesomeIcon icon={faBook} /> {bookRows.length}
                            </Button>
                        </ButtonGroup>
                    </Col>
                </Row>
                {error}
            </Form>
            <BookTable books={bookRows} realMatches={realMatches} />
        </div>
    );
}

export default App;
