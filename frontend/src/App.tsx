import React, { useState, useRef, useEffect, JSX } from "react";
import "./App.css";
import { Table, Form, Row, Col, Input, Button, ButtonGroup } from "reactstrap";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBarsStaggered, faBook } from "@fortawesome/free-solid-svg-icons";
import Books from "./books.json";

const searchableBooks = Books.books.map((b) => ({
    book: b,
    haystack: `${b.author} ${b.title} ${b.loc} ${b.zone}`,
}));

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
                    <td>{book.zone}</td>
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
                    <th>/</th>
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
    const [debouncedSearch, setDebouncedSearch] = useState<string>("");
    const [bookRows, setBookRows] = useState<typeof Books.books>(Books.books);
    const [realMatches, setRealMatches] = useState<Set<number>>(new Set());
    const [fuzzy, setFuzzy] = useState<boolean>(false);
    const [error, setError] = useState<string | null>();

    useEffect(() => {
        const id = setTimeout(() => setDebouncedSearch(searchString), 200);
        return () => clearTimeout(id);
    }, [searchString]);

    React.useEffect(() => {
        let re: RegExp;
        try {
            re = new RegExp(debouncedSearch, "i");
            setError(null);
        } catch (e: any) {
            setError(e.toString());
            re = new RegExp("^.*$", "i");
        }

        const realMatches = new Set<number>();
        const matchingBooks: typeof Books.books = [];
        const matchingIndices = new Set<number>();

        for (let i = 0; i < searchableBooks.length; i++) {
            if (re.test(searchableBooks[i].haystack)) {
                matchingIndices.add(i);
            }
        }

        for (let i = 0; i < searchableBooks.length; i++) {
            const { book } = searchableBooks[i];
            if (matchingIndices.has(i)) {
                matchingBooks.push(book);
                if (fuzzy) realMatches.add(book.books_id);
            } else if (fuzzy) {
                for (let j = 1; j < 3; j++) {
                    if (matchingIndices.has(i + j) || matchingIndices.has(i - j)) {
                        matchingBooks.push(book);
                        break;
                    }
                }
            }
        }

        setRealMatches(realMatches);
        setBookRows(matchingBooks);
    }, [debouncedSearch, fuzzy]);

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
