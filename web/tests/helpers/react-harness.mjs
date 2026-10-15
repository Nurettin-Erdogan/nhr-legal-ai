import { readFileSync } from "node:fs";
import ts from "typescript";

/** Component event regression harness; services/effects are deterministic, no browser/model needed. */
export function componentView(file, exported, initialProps, mocks) {
  let slots = [],
    cursor = 0,
    pending = [],
    key;
  const jsx = (type, props, key) => ({ type, props, key });
  const ui = new Proxy({}, { get: (_, name) => String(name) });
  const react = {
    useState(initial) {
      const index = cursor++,
        values = slots;
      if (!(index in values)) values[index] = typeof initial === "function" ? initial() : initial;
      return [
        values[index],
        (value) => {
          values[index] = typeof value === "function" ? value(values[index]) : value;
        },
      ];
    },
    useRef(initial) {
      return (slots[cursor++] ??= { current: initial });
    },
    useCallback(callback, dependencies) {
      const index = cursor++,
        previous = slots[index];
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i])))
        slots[index] = { callback, dependencies };
      return slots[index].callback;
    },
    useEffect(effect, dependencies) {
      const index = cursor++,
        previous = slots[index];
      if (
        !previous ||
        dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))
      ) {
        const entry = (slots[index] = { dependencies, cleanup: previous?.cleanup });
        pending.push(() => {
          entry.cleanup?.();
          entry.cleanup = effect();
        });
      }
    },
  };
  const deps = { react, "react/jsx-runtime": { jsx, jsxs: jsx }, ...mocks };
  const code = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(
    (name) => {
      if (name in deps) return deps[name];
      if (name.startsWith("@/components/") || name === "lucide-react") return ui;
      throw new Error("Unexpected dependency " + name);
    },
    module,
    module.exports,
  );
  function unmount() {
    for (const slot of slots) slot?.cleanup?.();
  }
  function render(props = initialProps) {
    const outer = module.exports[exported](props);
    if (key !== outer.key) {
      unmount();
      slots = [];
      key = outer.key;
    }
    cursor = 0;
    pending = [];
    const tree = typeof outer.type === "function" ? outer.type(outer.props) : outer;
    for (const effect of pending) effect();
    return tree;
  }
  return { render, unmount };
}
export function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...nodes(tree.props?.children)];
}
export const settle = () => new Promise((resolve) => setImmediate(resolve));
