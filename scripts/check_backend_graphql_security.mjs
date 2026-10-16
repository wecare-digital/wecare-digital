import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(new URL('../amplify/package.json', import.meta.url));
const lock = JSON.parse(readFileSync(new URL('../amplify/package-lock.json', import.meta.url)));
const copies = Object.entries(lock.packages).filter(([path]) => path.endsWith('/@graphql-tools/utils'));
assert.ok(copies.length > 0, 'Backend utility dependency must be present');
for (const [path, entry] of copies) assert.equal(entry.version, '12.0.1', path);

const { buildSchema, printSchema } = require('graphql');
const { mergeSchemas } = require('@graphql-tools/schema');
const { mergeDeep } = require('@graphql-tools/utils');
const merged = mergeSchemas({ schemas: [
  buildSchema('type Query { hello: String }'),
  buildSchema('type Mutation { create: String }'),
] });
assert.match(printSchema(merged), /hello: String/);
assert.match(printSchema(merged), /create: String/);

// Use a harmless sentinel rather than replacing built-in methods in this process.
const payload = JSON.parse('{"__proto__":{"wecarePolluted":true},"constructor":{"prototype":{"wecarePolluted":true}},"safe":{"value":1}}');
mergeDeep([{}, payload]);
assert.equal(Object.prototype.wecarePolluted, undefined);
assert.equal(Function.prototype.wecarePolluted, undefined);

// Exercise the actual Amplify generator callers that previously resolved older utils majors.
const { generateStatements, generateTypes } = require('@aws-amplify/graphql-generator');
const schema = 'type Todo { id: ID! title: String! } type Query { getTodo(id: ID!): Todo }';
const statements = await generateStatements({ schema, target: 'typescript' });
assert.match(Object.values(statements).join('\n'), /getTodo/);
const types = await generateTypes({ schema, target: 'typescript',
  queries: 'query GetTodo($id: ID!) { getTodo(id: $id) { id title } }' });
assert.match(Object.values(types).join('\n'), /GetTodo/);
console.log(`PASS: ${copies.length} patched utility location(s), schema merge, prototype guard and Amplify statement/type generation`);
