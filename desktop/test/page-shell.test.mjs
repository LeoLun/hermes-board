import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/board-page.js', import.meta.url), 'utf8');

test('board page does not project controls into the workspace page header', () => {
  assert.doesNotMatch(source, /WorkspacePageHeaderControl|HeaderControl/);
  assert.doesNotMatch(source, /h\(Header,/);
});

test('empty board keeps an inline add-card action', () => {
  assert.match(source, /title: '看板上还没有卡片',\s*actions:/);
  assert.match(source, /h\(AddCardButton,/);
});

test('non-empty board keeps add and arrange actions outside the page header', () => {
  assert.match(source, /className: 'hb-floating-actions'/);
  assert.match(source, /h\(AddCardButton,[\s\S]*h\(ArrangeButton,/);
});
