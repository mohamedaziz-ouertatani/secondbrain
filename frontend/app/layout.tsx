import type { Metadata } from "next";
import { Suspense } from "react";
import "@fontsource/noto-sans/400.css";
import "@fontsource/noto-sans/500.css";
import "@fontsource/noto-sans/600.css";
import "@fontsource/noto-sans-arabic/400.css";
import "@fontsource/noto-sans-arabic/600.css";
import "@fontsource/courier-prime/400.css";
import "@fontsource/courier-prime/700.css";
import "./globals.css";
import { CaptureDialog } from "@/components/CaptureDialog";
import { Rail } from "@/components/Rail";

export const metadata: Metadata = {
  title: "Sikimi",
  description: "Ask your course material; every answer cites its page",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <div className="app">
          <Suspense>
            <Rail />
          </Suspense>
          <main className="main">{children}</main>
          <Suspense>
            <CaptureDialog />
          </Suspense>
        </div>
      </body>
    </html>
  );
}
