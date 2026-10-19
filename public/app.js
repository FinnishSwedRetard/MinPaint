const WIDTH = 1920;
const HEIGHT = 1080;
const POLL_INTERVAL_MS = 2_000;
const canvas = document.querySelector("#canvas");
const context = canvas.getContext("2d", { alpha: false });
const image = context.createImageData(WIDTH, HEIGHT);
image.data.fill(255);
const viewport = document.querySelector("#canvas-viewport");
const loading = document.querySelector("#loading");
const count = document.querySelector("#painted-count");
const cooldownLabel = document.querySelector("#cooldown");
const statusMessage = document.querySelector("#status-message");
const coordinates = document.querySelector("#coordinates");
const colorPicker = document.querySelector("#color-picker");
const colorValue = document.querySelector("#color-value");
const zoomLabel = document.querySelector("#zoom-level");
const MIN_ZOOM = 1;
const MAX_ZOOM = 16;
const ZOOM_STEP = 1.25;

let sequence = 0;
let paintedPixels = 0;
let nextPaintAt = 0;
let busy = false;
let pollTimer;
let zoom = MIN_ZOOM;
let dragStart = null;
let didDrag = false;
const paintedIndexes = new Set();

function hexToRgb(color) {
  return [
    Number.parseInt(color.slice(1, 3), 16),
    Number.parseInt(color.slice(3, 5), 16),
    Number.parseInt(color.slice(5, 7), 16),
  ];
}

function paintPixel(index, color) {
  const offset = Number(index) * 4;
  const [red, green, blue] = hexToRgb(color);
  image.data[offset] = red;
  image.data[offset + 1] = green;
  image.data[offset + 2] = blue;
  image.data[offset + 3] = 255;
  context.putImageData(image, 0, 0, index % WIDTH, Math.floor(index / WIDTH), 1, 1);
  if (!paintedIndexes.has(index)) {
    paintedIndexes.add(index);
    paintedPixels += 1;
  }
}

function applySnapshot(board) {
  image.data.fill(255);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, WIDTH, HEIGHT);
  paintedPixels = 0;
  paintedIndexes.clear();
  for (const [index, color] of Object.entries(board.pixels)) {
    const offset = Number(index) * 4;
    const [red, green, blue] = hexToRgb(color);
    image.data[offset] = red;
    image.data[offset + 1] = green;
    image.data[offset + 2] = blue;
    image.data[offset + 3] = 255;
    paintedIndexes.add(Number(index));
    paintedPixels += 1;
  }
  context.putImageData(image, 0, 0);
  sequence = board.sequence;
  nextPaintAt = board.nextPaintAt;
  count.textContent = paintedPixels.toLocaleString();
  updateCooldown();
}

async function fetchBoard() {
  const response = await fetch("/api/board", { cache: "no-store" });
  if (!response.ok) throw new Error("Could not load the shared canvas.");
  applySnapshot(await response.json());
}

async function pollChanges() {
  const response = await fetch(`/api/changes?after=${sequence}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Could not check for new pixels.");
  const result = await response.json();
  if (result.reset) {
    await fetchBoard();
    return;
  }
  for (const change of result.changes) paintPixel(change.index, change.color);
  sequence = result.sequence;
  count.textContent = paintedPixels.toLocaleString();
}

function updateCooldown() {
  const remaining = Math.max(0, nextPaintAt - Date.now());
  if (remaining === 0) {
    cooldownLabel.innerHTML = 'READY <span class="ready-dot"></span>';
    return;
  }
  const seconds = Math.ceil(remaining / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  cooldownLabel.textContent = `${minutes}:${String(rest).padStart(2, "0")}`;
}

function canvasPosition(event) {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(WIDTH - 1, Math.floor((event.clientX - bounds.left) * WIDTH / bounds.width))),
    y: Math.max(0, Math.min(HEIGHT - 1, Math.floor((event.clientY - bounds.top) * HEIGHT / bounds.height))),
  };
}

function setZoom(nextZoom, anchorX = viewport.clientWidth / 2, anchorY = viewport.clientHeight / 2) {
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
  if (next === zoom) return;

  const oldWidth = canvas.getBoundingClientRect().width;
  const oldHeight = canvas.getBoundingClientRect().height;
  const pointX = (viewport.scrollLeft + anchorX) / oldWidth;
  const pointY = (viewport.scrollTop + anchorY) / oldHeight;
  zoom = next;
  canvas.style.width = `${zoom * 100}%`;

  const newWidth = canvas.getBoundingClientRect().width;
  const newHeight = canvas.getBoundingClientRect().height;
  viewport.scrollLeft = pointX * newWidth - anchorX;
  viewport.scrollTop = pointY * newHeight - anchorY;
  zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
  canvas.classList.toggle("zoomed", zoom > MIN_ZOOM);
}

document.querySelector("#zoom-in").addEventListener("click", () => setZoom(zoom * ZOOM_STEP));
document.querySelector("#zoom-out").addEventListener("click", () => setZoom(zoom / ZOOM_STEP));
document.querySelector("#zoom-reset").addEventListener("click", () => {
  setZoom(MIN_ZOOM);
  viewport.scrollTo({ left: 0, top: 0 });
});

viewport.addEventListener("wheel", (event) => {
  event.preventDefault();
  const bounds = viewport.getBoundingClientRect();
  const direction = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
  setZoom(zoom * direction, event.clientX - bounds.left, event.clientY - bounds.top);
}, { passive: false });

canvas.addEventListener("pointerdown", (event) => {
  if (zoom === MIN_ZOOM || event.button !== 0) return;
  dragStart = {
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    scrollLeft: viewport.scrollLeft,
    scrollTop: viewport.scrollTop,
  };
  didDrag = false;
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (dragStart?.pointerId === event.pointerId) {
    const deltaX = event.clientX - dragStart.x;
    const deltaY = event.clientY - dragStart.y;
    if (Math.abs(deltaX) + Math.abs(deltaY) > 4) didDrag = true;
    if (didDrag) {
      viewport.scrollLeft = dragStart.scrollLeft - deltaX;
      viewport.scrollTop = dragStart.scrollTop - deltaY;
      return;
    }
  }
  const { x, y } = canvasPosition(event);
  coordinates.textContent = `X ${String(x).padStart(4, "0")} · Y ${String(y).padStart(4, "0")}`;
});

function stopDragging(event) {
  if (dragStart?.pointerId === event.pointerId) {
    dragStart = null;
    if (event.type === "pointercancel") didDrag = false;
  }
}

canvas.addEventListener("pointerup", stopDragging);
canvas.addEventListener("pointercancel", stopDragging);

canvas.addEventListener("pointerleave", () => {
  if (!dragStart) coordinates.textContent = "FIND YOUR PIXEL";
});

canvas.addEventListener("click", async (event) => {
  if (didDrag) {
    didDrag = false;
    return;
  }
  if (busy) return;
  if (Date.now() < nextPaintAt) {
    updateCooldown();
    statusMessage.textContent = `Your next pixel is ready in ${cooldownLabel.textContent}.`;
    return;
  }
  const { x, y } = canvasPosition(event);
  busy = true;
  statusMessage.textContent = "Saving your pixel…";
  try {
    const response = await fetch("/api/paint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ x, y, color: colorPicker.value }),
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 429) nextPaintAt = result.nextPaintAt;
      throw new Error(result.error || "Your pixel could not be saved.");
    }
    paintPixel(result.index, result.color);
    sequence = Math.max(sequence, result.sequence);
    nextPaintAt = result.nextPaintAt;
    count.textContent = paintedPixels.toLocaleString();
    statusMessage.textContent = `Pixel placed at ${x}, ${y}. See you in a minute.`;
  } catch (error) {
    statusMessage.textContent = error.message;
  } finally {
    busy = false;
    updateCooldown();
  }
});

colorPicker.addEventListener("input", () => {
  colorValue.textContent = colorPicker.value.toUpperCase();
  document.querySelectorAll(".swatch").forEach((swatch) => {
    swatch.classList.toggle("selected", swatch.dataset.color.toLowerCase() === colorPicker.value.toLowerCase());
  });
});

document.querySelectorAll(".swatch").forEach((swatch) => {
  swatch.addEventListener("click", () => {
    colorPicker.value = swatch.dataset.color;
    colorPicker.dispatchEvent(new Event("input", { bubbles: true }));
  });
});

async function connect() {
  try {
    await fetchBoard();
    loading.classList.add("hidden");
    pollTimer = window.setInterval(async () => {
      try {
        await pollChanges();
      } catch (error) {
        statusMessage.textContent = error.message;
      }
    }, POLL_INTERVAL_MS);
  } catch (error) {
    loading.innerHTML = `<span>${error.message} Refresh the page to try again.</span>`;
    statusMessage.textContent = error.message;
  }
}

window.setInterval(updateCooldown, 250);
window.addEventListener("beforeunload", () => window.clearInterval(pollTimer));
connect();
