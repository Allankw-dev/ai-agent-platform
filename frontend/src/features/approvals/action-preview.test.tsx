import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActionPreview } from "@/features/approvals/action-preview";

describe("ActionPreview", () => {
  describe("a Slack message", () => {
    const input = { channel: "C0123456789", text: "Deploy finished\nAll green" };

    it("shows the channel and the final text, line breaks kept", () => {
      const { container } = render(<ActionPreview toolKey="slack.send_message" input={input} />);
      expect(screen.getByText("Channel")).toBeInTheDocument();
      expect(screen.getByText("C0123456789", { selector: "code" })).toBeInTheDocument();
      const message = container.querySelector("dl p") as HTMLElement;
      expect(message.textContent).toBe("Deploy finished\nAll green");
      expect(message.className).toMatch(/whitespace-pre-wrap/);
      expect(screen.getByText(/Mentions such as @channel are disabled/)).toBeInTheDocument();
    });

    it("shows agent-written markup as plain text, never as markup", () => {
      const nasty = { channel: "C0123456789", text: '<img src=x onerror="alert(1)"> <b>hi</b>' };
      const { container } = render(<ActionPreview toolKey="slack.send_message" input={nasty} />);
      expect(container.querySelector("img")).toBeNull();
      expect(container.querySelector("b")).toBeNull();
      expect((container.querySelector("dl p") as HTMLElement).textContent).toBe(nasty.text);
    });

    it("keeps invisible characters the platform added, so the text is exactly what is sent", () => {
      const text = "@\u200bchannel hello";
      const { container } = render(
        <ActionPreview toolKey="slack.send_message" input={{ channel: "C1", text }} />,
      );
      expect((container.querySelector("dl p") as HTMLElement).textContent).toBe(text);
    });
  });

  describe("an HTTP write", () => {
    const input = {
      method: "DELETE",
      url: "https://api.example.com/orders/7?force=1",
      headers: [
        { name: "Accept", value: "application/json" },
        { name: "X-Trace", value: "abc" },
      ],
      body: '{"reason": "duplicate"}',
      content_type: "application/json",
    };

    it("shows the method, the URL as text, the headers and the body", () => {
      render(<ActionPreview toolKey="http.request" input={input} />);
      expect(screen.getByText("DELETE")).toBeInTheDocument();
      expect(screen.getByText("https://api.example.com/orders/7?force=1")).toBeInTheDocument();
      expect(screen.getByText("Accept: application/json")).toBeInTheDocument();
      expect(screen.getByText("X-Trace: abc")).toBeInTheDocument();
      expect(screen.getByText("Body (application/json)")).toBeInTheDocument();
      expect(screen.getByText('{"reason": "duplicate"}')).toBeInTheDocument();
    });

    it("never makes the URL clickable", () => {
      render(<ActionPreview toolKey="http.request" input={input} />);
      expect(screen.queryByRole("link")).toBeNull();
    });

    it("says the platform adds the credential and that the person never sees it", () => {
      render(<ActionPreview toolKey="http.request" input={input} />);
      expect(screen.getByText(/adds the integration's saved credential/)).toBeInTheDocument();
    });

    it("leaves out headers and body when there are none", () => {
      render(
        <ActionPreview
          toolKey="http.request"
          input={{ method: "POST", url: "https://api.example.com/x" }}
        />,
      );
      expect(screen.queryByText("Headers")).toBeNull();
      expect(screen.queryByText(/^Body/)).toBeNull();
    });
  });

  describe("any other tool", () => {
    it("has no special rows, only the exact data", () => {
      render(<ActionPreview toolKey="utility.calculate" input={{ expression: "7 * 6" }} />);
      expect(screen.queryByText("Channel")).toBeNull();
      expect(screen.queryByText("Method")).toBeNull();
      expect(screen.getByText("Exact data")).toBeInTheDocument();
    });
  });

  it("always includes the exact data, as the same JSON the engine will run", () => {
    const input = { channel: "C0123456789", text: "Hi" };
    const { container } = render(<ActionPreview toolKey="slack.send_message" input={input} />);
    const pre = container.querySelector("details pre");
    expect(pre?.textContent).toBe(JSON.stringify(input, null, 2));
    const summary = within(container.querySelector("details") as HTMLElement).getByText(
      "Exact data",
    );
    expect(summary.tagName).toBe("SUMMARY");
  });
});
