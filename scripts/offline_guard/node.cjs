// Opt-in test/build subprocess barrier; no changes to the running app/server.
if (process.env.NHR_OFFLINE_AUDIT === "1") {
  const net = require("node:net");
  const originalConnect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function (...args) {
    // Preserve named-pipe IPC, but never allow a real TCP request (even to
    // localhost, where a running app could proxy a paid provider call).
    const first = args[0];
    const pipe = typeof first === "string" && !/^\d+$/.test(first)
      || first && typeof first === "object" && typeof first.path === "string";
    if (pipe) return originalConnect.apply(this, args);
    throw new Error("OFFLINE_AUDIT: real TCP access is disabled");
  };
}
