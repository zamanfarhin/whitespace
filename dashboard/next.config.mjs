/** @type {import('next').NextConfig} */
export default {
  // Static export so the dashboard deploys anywhere and needs no server.
  // The pipeline writes public/leads.json; the UI is a pure consumer of it.
  output: "export",
  images: { unoptimized: true },
};
