// Tiny element helper so the Desktop sources stay plain ESM (no JSX): h(type, props, ...children).
import { jsx, jsxs } from 'react/jsx-runtime';

export function h(type, props, ...children) {
  const { key, ...rest } = props || {};
  const kids = children.filter((c) => c !== undefined);
  if (kids.length === 1) rest.children = kids[0];
  else if (kids.length > 1) rest.children = kids;
  return (kids.length > 1 ? jsxs : jsx)(type, rest, key);
}
