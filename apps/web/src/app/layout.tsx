import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ObservAInova — Ciência para problemas públicos",
  description:
    "Ecossistema de interação que conecta problemas públicos a contribuições científicas validadas.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>
        <header className="site-header">
          <a className="brand" href="/" aria-label="ObservAInova — página inicial">
            <span className="brand__mark" aria-hidden="true">O</span>
            <span>observ<span>AI</span>nova</span>
          </a>
          <span className="header-note">Pernambuco · Ciência aplicada ao território</span>
        </header>
        <main>{children}</main>
        <footer>
          <p>Um ecossistema de interação entre demandas públicas e conhecimento científico.</p>
        </footer>
      </body>
    </html>
  );
}
