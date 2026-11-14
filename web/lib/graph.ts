// Ported from mockups-v2/shared/graph.js: seeded layout and 1-bit print helpers.
// The old fictional curve and ticket fixtures are deliberately not carried over.
// DOM access is confined to rendering functions; importing this module is SSR-safe.

export interface PlateNode {
  id: string;
  label?: string;
  x: number;
  y: number;
  deg?: number;
  r?: number;
}

export interface PlateEdge {
  s: number;
  t: number;
  w: number;
  key?: boolean;
}

export interface PlateGraph {
  nodes: readonly PlateNode[];
  edges: readonly PlateEdge[];
}

export interface PlateOptions {
  mode?: "atkinson" | "halftone";
  ink?: string;
  paper?: string;
  cell?: number;
  screen?: number;
  pad?: number;
  scale?: number;
  edgeAlpha?: number;
  edgeW?: number;
  nodeR?: number;
  glow?: number;
  gain?: number;
  noise?: number;
  seed?: number;
}

interface GeneratedNode extends PlateNode {
  pin: boolean;
  deg: number;
  r: number;
  c: number;
  vx: number;
  vy: number;
}

export interface GraphOptions {
  seed?: number;
  pinned?: (PlateNode & { r?: number })[];
  clusters?: { x: number; y: number; n: number; spread: number; squash?: number; hub?: string }[];
  links?: [string, string, number?, string?][];
  cross?: number;
  iters?: number;
}

export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = t + Math.imul(t ^ (t >>> 7), 61 | t) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function makeGraph(options: GraphOptions) {
  const random = rng(options.seed ?? 7);
  const nodes: GeneratedNode[] = [];
  const edges: (PlateEdge & { kind?: string })[] = [];
  const byId: Record<string, GeneratedNode> = {};

  for (const pinned of options.pinned ?? []) {
    const node: GeneratedNode = {
      ...pinned, pin: true, deg: 0, r: pinned.r ?? 1, c: -1, vx: 0, vy: 0,
    };
    nodes.push(node);
    byId[node.id] = node;
  }

  (options.clusters ?? []).forEach((cluster, ci) => {
    const start = nodes.length;
    for (let i = 0; i < cluster.n; i++) {
      const angle = random() * Math.PI * 2;
      const distance = Math.pow(random(), 0.7) * cluster.spread;
      const node: GeneratedNode = {
        id: `c${ci}_${i}`,
        x: cluster.x + Math.cos(angle) * distance,
        y: cluster.y + Math.sin(angle) * distance * (cluster.squash ?? 1),
        pin: false, deg: 0, r: 0.4 + random() * 0.8, c: ci, vx: 0, vy: 0,
      };
      nodes.push(node);
      byId[node.id] = node;
      if (i > 0) {
        const me = nodes.length - 1;
        const candidates = nodes.slice(start, me).map((candidate, index) => ({
          index: start + index,
          distance: (candidate.x - node.x) ** 2 + (candidate.y - node.y) ** 2,
        })).sort((a, b) => a.distance - b.distance);
        edges.push({ s: me, t: candidates[0].index, w: 0.35 + random() * 0.5 });
        if (candidates.length > 2 && random() < 0.55) {
          edges.push({
            s: me, t: candidates[1 + Math.floor(random() * 2)].index,
            w: 0.2 + random() * 0.4,
          });
        }
        if (random() < 0.08) edges.push({ s: me, t: start, w: 0.3 });
      }
    }
    const hub = cluster.hub ? byId[cluster.hub] : undefined;
    if (hub) {
      for (let i = 0; i < Math.min(6, cluster.n); i++) {
        edges.push({ s: nodes.indexOf(hub), t: start + Math.floor(random() * cluster.n), w: 0.5 });
      }
    }
  });

  for (let i = 0; i < (options.cross ?? 20); i++) {
    const s = Math.floor(random() * nodes.length);
    const t = Math.floor(random() * nodes.length);
    if (s !== t) edges.push({ s, t, w: 0.15 + random() * 0.2 });
  }
  for (const [from, to, weight, kind] of options.links ?? []) {
    const s = nodes.indexOf(byId[from]);
    const t = nodes.indexOf(byId[to]);
    if (s >= 0 && t >= 0) edges.push({ s, t, w: weight ?? 0.8, kind, key: true });
  }

  // Retained for future tooling. Shipped plates should use the precomputed JSON.
  const iterations = options.iters ?? 120;
  for (let step = 0; step < iterations; step++) {
    const cool = 1 - step / iterations;
    for (const node of nodes) {
      if (node.pin) continue;
      let fx = 0;
      let fy = 0;
      for (const other of nodes) {
        if (node === other) continue;
        const dx = node.x - other.x;
        const dy = node.y - other.y;
        const d2 = dx * dx + dy * dy + 1e-5;
        if (d2 < 0.02) {
          fx += dx / d2 * 0.0009 * 0.06;
          fy += dy / d2 * 0.0009 * 0.06;
        }
      }
      node.vx = fx * cool;
      node.vy = fy * cool;
    }
    for (const edge of edges) {
      const a = nodes[edge.s];
      const b = nodes[edge.t];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const distance = Math.hypot(dx, dy) + 1e-6;
      const force = (distance - 0.045) * 0.02 * cool;
      if (!a.pin) { a.vx += dx / distance * force; a.vy += dy / distance * force; }
      if (!b.pin) { b.vx -= dx / distance * force; b.vy -= dy / distance * force; }
    }
    for (const node of nodes) {
      if (!node.pin) {
        node.x += Math.max(-0.01, Math.min(0.01, node.vx));
        node.y += Math.max(-0.01, Math.min(0.01, node.vy));
      }
    }
  }
  for (const edge of edges) { nodes[edge.s].deg++; nodes[edge.t].deg++; }
  return { nodes, edges, byId };
}

export function bigGraph(seed = 99) {
  const random = rng(seed);
  const centers = [
    [0.25, 0.3, 110], [0.62, 0.22, 90], [0.75, 0.62, 120],
    [0.4, 0.72, 100], [0.13, 0.74, 45], [0.52, 0.46, 60], [0.88, 0.2, 40],
  ];
  return makeGraph({
    seed, cross: 25, iters: 0,
    clusters: centers.map(([x, y, n]) => ({ x, y, n, spread: 0.11 + random() * 0.05 })),
  });
}

function context2d(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext("2d");
  if (!context) throw new Error("A 2D canvas context is required for print rendering.");
  return context;
}

export function toneField(graph: PlateGraph, width: number, height: number, options: PlateOptions = {}) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = context2d(canvas);
  const pad = options.pad ?? 0.06;
  const scale = options.scale ?? 1;
  const proj = (node: Pick<PlateNode, "x" | "y">) => ({
    x: (pad + node.x * (1 - 2 * pad)) * width,
    y: (pad + node.y * (1 - 2 * pad)) * height,
  });
  const degrees = new Uint32Array(graph.nodes.length);
  for (const edge of graph.edges) { degrees[edge.s]++; degrees[edge.t]++; }
  context.fillStyle = "#000";
  context.fillRect(0, 0, width, height);
  context.globalCompositeOperation = "lighter";
  for (const edge of graph.edges) {
    const a = proj(graph.nodes[edge.s]);
    const b = proj(graph.nodes[edge.t]);
    const alpha = (options.edgeAlpha ?? 0.35) * edge.w * (edge.key ? 1.6 : 1);
    context.strokeStyle = `rgba(255,255,255,${alpha})`;
    context.lineWidth = (edge.key ? 2.2 : 1.1) * scale * (options.edgeW ?? 1);
    context.beginPath();
    context.moveTo(a.x, a.y);
    context.lineTo(b.x, b.y);
    context.stroke();
  }
  graph.nodes.forEach((node, index) => {
    const point = proj(node);
    const radius = (options.nodeR ?? 7) * scale *
      (0.6 + Math.min(node.deg ?? degrees[index], 8) * 0.12) *
      (node.r ?? 1) * (node.label ? 1.6 : 1);
    // An offscreen density field only. The visible output is ink dots, never a gradient.
    const glow = options.glow ?? 0.55;
    const field = context.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius * 2.6);
    field.addColorStop(0, `rgba(255,255,255,${glow})`);
    field.addColorStop(0.35, `rgba(255,255,255,${glow * 0.45})`);
    field.addColorStop(1, "rgba(255,255,255,0)");
    context.fillStyle = field;
    context.beginPath();
    context.arc(point.x, point.y, radius * 2.6, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "rgba(255,255,255,0.95)";
    context.beginPath();
    context.arc(point.x, point.y, radius * 0.42, 0, Math.PI * 2);
    context.fill();
  });
  const pixels = context.getImageData(0, 0, width, height).data;
  const t = new Float32Array(width * height);
  for (let i = 0; i < t.length; i++) t[i] = Math.min(1, pixels[i * 4] / 255 * (options.gain ?? 1));
  return { t, proj };
}

/** Atkinson error diffusion. Copies the tone field so callers can reuse it. */
export function atkinson(tone: Float32Array, width: number, height: number, noise = 0.04, seed = 3) {
  const t = tone.slice();
  const pixels = new Uint8Array(width * height);
  const random = rng(seed);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      const old = t[i] + (random() - 0.5) * noise;
      const value = old > 0.5 ? 1 : 0;
      pixels[i] = value;
      const error = (old - value) / 8;
      if (x + 1 < width) t[i + 1] += error;
      if (x + 2 < width) t[i + 2] += error;
      if (y + 1 < height) {
        if (x > 0) t[i + width - 1] += error;
        t[i + width] += error;
        if (x + 1 < width) t[i + width + 1] += error;
      }
      if (y + 2 < height) t[i + 2 * width] += error;
    }
  }
  return pixels;
}

export function plate(canvas: HTMLCanvasElement, graph: PlateGraph, options: PlateOptions = {}) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(canvas.clientWidth * dpr));
  canvas.height = Math.max(1, Math.round(canvas.clientHeight * dpr));
  const context = context2d(canvas);
  const cell = Math.max(1, Math.round((options.cell ?? 1) * dpr));
  const width = Math.ceil(canvas.width / cell);
  const height = Math.ceil(canvas.height / cell);
  const field = toneField(graph, width, height, {
    ...options, scale: (options.scale ?? 1) * dpr / cell,
  });
  const ink = options.ink ?? "#1C1914";
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (options.paper) {
    context.fillStyle = options.paper;
    context.fillRect(0, 0, canvas.width, canvas.height);
  }
  if ((options.mode ?? "atkinson") === "atkinson") {
    const dots = atkinson(field.t, width, height, options.noise, options.seed);
    const color = ink.replace("#", "");
    const rgb = [0, 2, 4].map((offset) => parseInt(color.slice(offset, offset + 2), 16));
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (!dots[y * width + x]) continue;
        for (let yy = 0; yy < cell; yy++) {
          for (let xx = 0; xx < cell; xx++) {
            const px = x * cell + xx;
            const py = y * cell + yy;
            if (px >= canvas.width || py >= canvas.height) continue;
            const i = (py * canvas.width + px) * 4;
            image.data[i] = rgb[0];
            image.data[i + 1] = rgb[1];
            image.data[i + 2] = rgb[2];
            image.data[i + 3] = 255;
          }
        }
      }
    }
    context.putImageData(image, 0, 0);
  } else {
    const screen = Math.max(1, Math.round((options.screen ?? 5) * dpr / cell));
    context.fillStyle = ink;
    for (let y = 0; y < height; y += screen) {
      for (let x = 0; x < width; x += screen) {
        let sum = 0;
        let count = 0;
        for (let yy = 0; yy < screen && y + yy < height; yy++) {
          for (let xx = 0; xx < screen && x + xx < width; xx++) {
            sum += field.t[(y + yy) * width + x + xx];
            count++;
          }
        }
        const value = sum / count;
        if (value < 0.04) continue;
        const radius = Math.sqrt(value) * screen * cell * 0.62;
        context.beginPath();
        context.arc((x + screen / 2) * cell, (y + screen / 2) * cell, radius, 0, Math.PI * 2);
        context.fill();
      }
    }
  }
  return (node: Pick<PlateNode, "x" | "y">) => {
    const point = field.proj(node);
    return { x: point.x * cell / dpr, y: point.y * cell / dpr };
  };
}

export function grain(size = 256, alpha = 0.028, seed = 11): string {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const context = context2d(canvas);
  const image = context.createImageData(size, size);
  const random = rng(seed);
  for (let i = 0; i < size * size; i++) {
    const value = random() * 255;
    image.data[i * 4] = value;
    image.data[i * 4 + 1] = value;
    image.data[i * 4 + 2] = value;
    image.data[i * 4 + 3] = random() < 0.5 ? alpha * 255 : 0;
  }
  context.putImageData(image, 0, 0);
  return canvas.toDataURL();
}
