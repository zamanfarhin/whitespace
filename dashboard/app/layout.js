import "./globals.css";

export const metadata = {
  title: "Whitespace — Tedlar lead qualification",
  description:
    "Sourced, scored, and drafted sales leads for DuPont Tedlar Graphics & Signage, "
    + "built from public trade show data.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
