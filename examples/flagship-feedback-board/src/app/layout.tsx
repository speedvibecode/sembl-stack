import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Feedback Board",
  description: "Sembl Stack flagship feedback board example",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
