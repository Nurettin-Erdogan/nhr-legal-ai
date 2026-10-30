import assert from "node:assert/strict";
import test from "node:test";
import { componentView, nodes, settle } from "./helpers/react-harness.mjs";

function panel(overrides = {}) {
  let owner = "alice";
  const calls = { link: [], unlink: [], errors: [] };
  const documents = [
    {
      id: "direct",
      file_name: "Direct.txt",
      status: "ready",
      direct_linked: true,
      case_id: null,
      ocr: false,
    },
    {
      id: "case",
      file_name: "Case.txt",
      status: "ready",
      direct_linked: false,
      case_id: "case",
      ocr: true,
    },
    {
      id: "pending",
      file_name: "Scan.pdf",
      status: "pending",
      direct_linked: true,
      case_id: null,
      ocr: false,
    },
  ];
  const page = {
    project_id: "project",
    case_id: "case",
    total: 3,
    ready: 2,
    pending: 1,
    ocr: 1,
    failed: [],
    documents,
  };
  const view = componentView(
    new URL("../src/components/ProjectDocuments.tsx", import.meta.url),
    "ProjectDocuments",
    { projectId: "project" },
    {
      "@/components/AuthContext": { useAuth: () => ({ user: { id: owner } }) },
      "@/lib/router-compat": { Link: "Link" },
      "@/lib/project-documents": {
        getProjectDocuments: overrides.load ?? (async () => page),
        linkProjectDocuments: async (...args) => {
          calls.link.push(args);
          return { linked: 1, already_linked: 0 };
        },
        unlinkProjectDocument: async (...args) => {
          calls.unlink.push(args);
        },
      },
      sonner: { toast: { success: () => {}, error: (message) => calls.errors.push(message) } },
    },
  );
  return {
    ...view,
    calls,
    setOwner: (value) => {
      owner = value;
    },
  };
}
const button = (tree, text) =>
  nodes(tree).find(
    (node) => node.type === "Button" && JSON.stringify(node.props.children).includes(text),
  );

test("project UI selects only readable documents and hands off the exact project scope", async () => {
  const view = panel();
  view.render();
  await settle();
  button(view.render(), "Filtredeki aranabilirleri").props.onClick();
  const action = nodes(view.render()).find((node) => node.type === "DocumentWorkflowActions");
  assert.deepEqual(action.props.ids, ["direct", "case"]);
  assert.equal(action.props.officeProjectId, "project");
  assert.equal(
    nodes(view.render()).find(
      (node) => node.type === "Checkbox" && node.props["aria-label"] === "Scan.pdf belgesini seç",
    ).props.disabled,
    true,
  );
});

test("archive linking and explicit unlink confirmation call only association actions", async () => {
  const view = panel();
  view.render();
  await settle();
  button(view.render(), "Arşivden belge bağla").props.onClick();
  nodes(view.render())
    .find((node) => node.type === "CaseDocPicker")
    .props.onChange(["doc"]);
  button(view.render(), "belgeyi projeye bağla").props.onClick();
  await settle();
  assert.deepEqual(view.calls.link, [["project", ["doc"]]]);
  button(view.render(), "Bağlantıyı kaldır").props.onClick();
  assert.equal(nodes(view.render()).find((node) => node.type === "AlertDialog").props.open, true);
  nodes(view.render())
    .find((node) => node.type === "AlertDialogAction")
    .props.onClick({ preventDefault() {} });
  await settle();
  assert.deepEqual(view.calls.unlink, [["project", "direct"]]);
  assert.deepEqual(view.calls.errors, []);
});

test("late project list from another account cannot populate the new account view", async () => {
  let resolve,
    loads = 0;
  const response = new Promise((done) => {
    resolve = done;
  });
  const view = panel({ load: () => (++loads === 1 ? response : new Promise(() => {})) });
  view.render();
  view.setOwner("bob");
  view.render();
  // Only resolve the old operation; the new account remains in its own pending state.
  resolve({
    project_id: "project",
    case_id: null,
    total: 1,
    ready: 1,
    pending: 0,
    ocr: 0,
    failed: [],
    documents: [{ id: "private", file_name: "PRIVATE_OLD_USER", status: "ready" }],
  });
  await settle();
  assert.ok(!nodes(view.render()).some((node) => node.type === "Checkbox"));
  assert.ok(!JSON.stringify(view.render()).includes("PRIVATE_OLD_USER"));
  assert.deepEqual(view.calls.errors, []);
});
