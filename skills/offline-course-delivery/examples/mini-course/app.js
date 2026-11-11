"use strict";

const storageKey = "peaskill-mini-course-notes-v1";
const courseId = "mean-demo";
const maxNoteLength = 50000;
// JSON.stringify needs at most six UTF-8 bytes per UTF-16 code unit
// (for example, a control character becomes "\u0001"). The spare 1 KiB
// covers the fixed fields and indentation, so every valid export fits import.
const maxBackupBytes = 6 * maxNoteLength + 1024;
const notes = document.querySelector("#notes");
const status = document.querySelector("#status");
const importStatus = document.querySelector("#import-status");

function validateBackup(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || value.schemaVersion !== 1 || value.courseId !== courseId
      || typeof value.notes !== "string" || value.notes.length > maxNoteLength) {
    throw new Error("invalid backup");
  }
  return { schemaVersion: 1, courseId, notes: value.notes };
}

function persist(value) {
  const backup = validateBackup({ schemaVersion: 1, courseId, notes: value });
  localStorage.setItem(storageKey, JSON.stringify(backup));
}

try {
  const previous = localStorage.getItem(storageKey);
  if (previous !== null) notes.value = validateBackup(JSON.parse(previous)).notes;
} catch {
  status.textContent = "本地笔记无法读取；原记录保持不变，可先导入有效备份。";
}

notes.addEventListener("input", () => {
  try {
    persist(notes.value);
    status.textContent = "已保存到当前浏览器";
  } catch {
    status.textContent = "保存失败，请导出备份；当前文本仍在页面中。";
  }
});

document.querySelector("#run-example").addEventListener("click", () => {
  const values = [2, 4, 6];
  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  document.querySelector("#result").textContent = `平均数：${mean}`;
});

document.querySelector("#export-backup").addEventListener("click", () => {
  const backup = validateBackup({ schemaVersion: 1, courseId, notes: notes.value });
  const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
  if (blob.size > maxBackupBytes) {
    status.textContent = "备份超出大小限制，未导出；当前笔记保持不变。";
    return;
  }
  const objectURL = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectURL;
  link.download = "mini-course-notes.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
});

document.querySelector("#import-backup").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > maxBackupBytes) throw new Error("backup too large");
    const backup = validateBackup(JSON.parse(await file.text()));
    // Validate the whole backup before changing storage or the current text.
    persist(backup.notes);
    notes.value = backup.notes;
    status.textContent = "已保存到当前浏览器";
    importStatus.textContent = "备份导入成功";
  } catch {
    importStatus.textContent = "备份无效或无法保存，原笔记保持不变。";
  } finally {
    event.target.value = "";
  }
});

fetch("numbers.py")
  .then((response) => {
    if (!response.ok) throw new Error("missing source");
    return response.text();
  })
  .then((source) => { document.querySelector("#code").textContent = source; })
  .catch(() => { document.querySelector("#code").textContent = "本地附件读取失败。请通过本地 HTTP 服务打开课程。"; });
