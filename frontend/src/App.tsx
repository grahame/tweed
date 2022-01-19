import React, { useState, useRef, useEffect } from 'react';
import './App.css';
import { Table, Form, Row, Col, Input, Badge } from 'reactstrap';
import Books from './books.json';

function useInput() {
    const [value, setValue] = useState<string>("");
    const inputReference = useRef<HTMLInputElement>(null);

    useEffect(() => {
        inputReference.current?.focus();
    }, []);

    const input = <Input innerRef={inputReference} className="bg-dark text-light" value={value} onChange={e => setValue(e.target.value)} type='text' />;
    return [value, input];
}

interface BookProp {
    books: typeof Books.books
};

function filterBook(book: typeof Books.books[0], re: RegExp) {
    return re.test(book.author) || re.test(book.title) || re.test(book.loc);
};

function BookTable(props: React.PropsWithChildren<BookProp>) {
    const tableRows = () => {
        return props.books.map((book) => (
            <tr key={book.books_id}>
                <td>{book.loc}</td>
                <td>{book.ddc}</td>
                <td>{book.author}</td>
                <td>{book.title}</td>
                <td>{book.isbn}</td>
                <td>{book.date}</td>
            </tr>
        ));
    };
    return <Table dark striped>
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
        <tbody>
            {tableRows()}
        </tbody>
    </Table>;
}

function App() {
    const [searchString, searchStringInput] = useInput();
    var error = "";
    var re: RegExp;
    try {
        re = new RegExp(searchString.toString(), 'i');
    } catch (e) {
        error = e.toString();
        re = new RegExp('^.*$', 'i');
    }
    const book_rows = Books.books.filter(book => filterBook(book, re));

    return <div>
        <Form>
            <Row className="bg-dark">
                <Col xs={{ size: 9, offset: 1 }}>
                    {searchStringInput}
                </Col>
                <Col xs={{ size: 1 }}>
                    <Badge pill>{book_rows.length}</Badge>
                </Col>
            </Row>
            {error}
        </Form>
        <BookTable books={book_rows} />
    </div>;
}

export default App;
