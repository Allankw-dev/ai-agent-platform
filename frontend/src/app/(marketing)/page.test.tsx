import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/(marketing)/page";

describe("Landing page", () => {
  it("renders the headline and every section", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { level: 1, name: /AI agents that do real work/ }),
    ).toBeInTheDocument();
    for (const name of [
      "Built for real operations",
      "How it works",
      "Designed for least privilege",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
  });

  it("links to the sections and the status page, and every link has a target", () => {
    render(<Home />);
    expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/register");
    expect(screen.getByRole("link", { name: "See how it works" })).toHaveAttribute(
      "href",
      "/#how-it-works",
    );
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toBeTruthy();
    }
  });
});
