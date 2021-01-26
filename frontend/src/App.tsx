import React, { useState, useRef, useEffect } from 'react';
import './App.css';
import { Form, Row, Col, Input, Badge } from 'reactstrap';
import Books from './books.json';
import DataGrid from 'react-data-grid';

const columns = [
    { key: 'ddc', name: 'DDC', filterable: true, width: 150 },
    { key: 'author', name: 'Author', filterable: true },
    { key: 'title', name: 'Title', filterable: true },
    { key: 'isbn', name: 'ISBN', filterable: true, width: 150 },
    { key: 'date', name: 'Date', filterable: true, width: 150 },
];

function useInput() {
    const [value, setValue] = useState<string>("");
    const inputReference = useRef<HTMLInputElement>(null);

    useEffect(() => {
        inputReference.current?.focus();
    }, []);

    const input = <Input innerRef={inputReference} className="bg-dark text-light" value={value} onChange={e => setValue(e.target.value)} type='text' />;
    return [value, input];
}

function filterBook(book: any, re: RegExp) {
    return re.test(book.author) || re.test(book.title);
};


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
    var rows = Books.books.filter(book => filterBook(book, re));
    return <div>
        <Form>
            <Row className="bg-dark">
                <Col xs={{ size: 9, offset: 1 }}>
                    {searchStringInput}
                </Col>
                <Col xs={{ size: 1 }}>
                    <Badge pill>{rows.length}</Badge>
                </Col>
            </Row>
            {error}
        </Form>
        <div className="grid-wrapper">
            <DataGrid
                style={{ height: "100%" }}
                columns={columns}
                rows={rows}
            />
        </div>
    </div>;
}

export default App;
