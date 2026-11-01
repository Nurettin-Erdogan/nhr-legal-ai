const requestId = new URL(location.href).searchParams.get("requestId") || "";
async function decide(approved) {
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = true;
  });
  await chrome.runtime.sendMessage({ type: "JURISAI_PAIRING_DECISION", requestId, approved });
  window.close();
}
document.getElementById("approve").addEventListener("click", () => decide(true));
document.getElementById("reject").addEventListener("click", () => decide(false));
