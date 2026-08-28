import type { Metadata } from "next";

import { PlaygroundPage } from "@/src/_pages/playground";

export const metadata: Metadata = {
  title: "Playground",
};

export default function Page() {
  return <PlaygroundPage />;
}
