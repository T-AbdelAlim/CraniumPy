// a small, deliberately constrained arithmetic expression parser/evaluator
// for the "Custom metrics" tab - numbers, + - * / ( ), and column-name
// identifiers only. NOT eval()/new Function(), even though this is a local
// desktop tool: a formula box is exactly the kind of input that eventually
// gets pasted-from-somewhere or handed to another user, and there's no
// legitimate use of a derived-metric formula that needs real code execution.
//
// parseFormula throws a SyntaxError (with a position-anchored message) on
// anything outside that grammar - used both to validate a formula as the
// user types it and to build the AST evaluateFormula walks per row.

const TOKEN_RE = /\s*(?:([0-9]+(?:\.[0-9]+)?)|([A-Za-z_][A-Za-z0-9_]*)|([+\-*/()]))/y;

function tokenize(source) {
  const tokens = [];
  let pos = 0;
  TOKEN_RE.lastIndex = 0;
  while (pos < source.length) {
    TOKEN_RE.lastIndex = pos;
    const m = TOKEN_RE.exec(source);
    if (!m || m.index !== pos) {
      const bad = source.slice(pos).trimStart()[0] ?? "";
      throw new SyntaxError(`unexpected character ${JSON.stringify(bad)} at position ${pos}`);
    }
    pos = TOKEN_RE.lastIndex;
    if (m[1] !== undefined) tokens.push({ type: "number", value: Number(m[1]) });
    else if (m[2] !== undefined) tokens.push({ type: "identifier", value: m[2] });
    else if (m[3] !== undefined) tokens.push({ type: m[3], value: m[3] });
  }
  return tokens;
}

// recursive-descent, standard precedence (unary minus > * / > + -).
class Parser {
  constructor(tokens) {
    this.tokens = tokens;
    this.pos = 0;
  }
  peek() {
    return this.tokens[this.pos];
  }
  next() {
    return this.tokens[this.pos++];
  }
  expect(type) {
    const t = this.next();
    if (!t || t.type !== type) {
      throw new SyntaxError(`expected ${JSON.stringify(type)}, got ${t ? JSON.stringify(t.value) : "end of formula"}`);
    }
    return t;
  }

  parseExpr() {
    let node = this.parseTerm();
    while (this.peek() && (this.peek().type === "+" || this.peek().type === "-")) {
      const op = this.next().type;
      node = { type: "binary", op, left: node, right: this.parseTerm() };
    }
    return node;
  }

  parseTerm() {
    let node = this.parseFactor();
    while (this.peek() && (this.peek().type === "*" || this.peek().type === "/")) {
      const op = this.next().type;
      node = { type: "binary", op, left: node, right: this.parseFactor() };
    }
    return node;
  }

  parseFactor() {
    const t = this.peek();
    if (!t) throw new SyntaxError("unexpected end of formula");
    if (t.type === "-") {
      this.next();
      return { type: "negate", operand: this.parseFactor() };
    }
    if (t.type === "(") {
      this.next();
      const node = this.parseExpr();
      this.expect(")");
      return node;
    }
    if (t.type === "number") {
      this.next();
      return { type: "number", value: t.value };
    }
    if (t.type === "identifier") {
      this.next();
      return { type: "identifier", name: t.value };
    }
    throw new SyntaxError(`unexpected token ${JSON.stringify(t.value)}`);
  }
}

// throws SyntaxError on empty/invalid input. returns an AST for evaluateFormula.
export function parseFormula(source) {
  const tokens = tokenize(source);
  if (tokens.length === 0) throw new SyntaxError("empty formula");
  const parser = new Parser(tokens);
  const ast = parser.parseExpr();
  if (parser.pos !== tokens.length) {
    throw new SyntaxError(`unexpected token ${JSON.stringify(parser.peek().value)} after end of expression`);
  }
  return ast;
}

// every column name the formula references - lets a caller validate "these
// all exist" up front, or list them in a hint, without re-walking the AST.
export function formulaColumns(ast) {
  const names = new Set();
  (function walk(node) {
    if (node.type === "identifier") names.add(node.name);
    else if (node.type === "negate") walk(node.operand);
    else if (node.type === "binary") {
      walk(node.left);
      walk(node.right);
    }
  })(ast);
  return names;
}

// evaluates against getValue(name) -> number|null. null propagates through
// the whole expression (a formula referencing a column that's blank for
// this row is blank for this row too, not zero) - same "sparse, not
// coerced" convention every other cohort-workspace numeric read follows
// (see lib/stats.js's toNumber). division by zero also yields null rather
// than Infinity/NaN, for the same "show nothing rather than something
// misleading" reason.
export function evaluateFormula(ast, getValue) {
  switch (ast.type) {
    case "number":
      return ast.value;
    case "identifier":
      return getValue(ast.name);
    case "negate": {
      const v = evaluateFormula(ast.operand, getValue);
      return v === null ? null : -v;
    }
    case "binary": {
      const l = evaluateFormula(ast.left, getValue);
      const r = evaluateFormula(ast.right, getValue);
      if (l === null || r === null) return null;
      switch (ast.op) {
        case "+": return l + r;
        case "-": return l - r;
        case "*": return l * r;
        case "/": return r === 0 ? null : l / r;
        default: return null;
      }
    }
    default:
      return null;
  }
}
