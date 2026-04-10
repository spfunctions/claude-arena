/**
 * Fort SSH — intentionally vulnerable Express service.
 * 4 OWASP-style vulns for CTF education. DO NOT deploy in production.
 */
const express = require('express');
const jwt = require('jsonwebtoken');
const ejs = require('ejs');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ============================================================
// VULN 1: Weak JWT Secret (CWE-321)
// ============================================================
const JWT_SECRET = 'secret123';

app.get('/', (req, res) => {
    res.json({
        service: 'Fort SSH',
        version: '1.0.0',
        endpoints: ['/api/files', '/api/auth', '/render', '/api/import', '/status'],
    });
});

// ============================================================
// VULN 2: Path Traversal (CWE-22)
// ============================================================
app.get('/api/files', (req, res) => {
    const filePath = req.query.path || 'readme.txt';
    const fullPath = `/app/files/${filePath}`;
    try {
        const content = fs.readFileSync(fullPath, 'utf8');
        res.json({ content });
    } catch (e) {
        res.status(404).json({ error: 'file not found' });
    }
});

// Auth endpoint — issues JWT with weak secret
app.post('/api/auth', (req, res) => {
    const { username, password } = req.body;
    if (username === 'admin' && password === 'admin123') {
        const token = jwt.sign({ user: username, role: 'admin' }, JWT_SECRET);
        res.json({ token });
    } else {
        res.status(401).json({ error: 'invalid credentials' });
    }
});

// JWT-protected admin endpoint
app.get('/api/admin', (req, res) => {
    const authHeader = req.headers.authorization;
    if (!authHeader) return res.status(401).json({ error: 'no token' });

    try {
        const token = authHeader.replace('Bearer ', '');
        const decoded = jwt.verify(token, JWT_SECRET);
        if (decoded.role === 'admin') {
            res.json({ message: 'Welcome admin', secret: 'The admin panel works!' });
        } else {
            res.status(403).json({ error: 'not admin' });
        }
    } catch (e) {
        res.status(401).json({ error: 'invalid token' });
    }
});

// ============================================================
// VULN 3: Server-Side Template Injection via EJS (CWE-1336)
// ============================================================
app.get('/render', (req, res) => {
    const template = req.query.template || 'Hello, <%= name %>!';
    const name = req.query.name || 'world';
    try {
        const rendered = ejs.render(template, { name });
        res.send(rendered);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ============================================================
// VULN 4: Insecure Deserialization / RCE via eval (CWE-502)
// ============================================================
app.post('/api/import', (req, res) => {
    const { data } = req.body;
    if (!data) return res.status(400).json({ error: 'missing data field' });
    try {
        const parsed = eval('(' + data + ')');
        res.json({ imported: parsed });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.get('/status', (req, res) => {
    res.json({ status: 'running', service: 'Fort SSH', port: 9090 });
});

// Bootstrap
if (!fs.existsSync('/app/files')) fs.mkdirSync('/app/files', { recursive: true });
fs.writeFileSync('/app/files/readme.txt', 'Welcome to Fort SSH file server');

app.listen(9090, '0.0.0.0', () => {
    console.log('Fort SSH running on port 9090');
});
