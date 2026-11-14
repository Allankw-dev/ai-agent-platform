import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepTimeline } from "@/features/runs/step-timeline";
import { step, STEPS } from "@/test/runs";

const item = (n: number) => screen.getByText(`Step ${n}`).closest("li") as HTMLElement;

describe("StepTimeline", () => {
  it("shows an empty message when nothing has happened yet", () => {
    render(<StepTimeline steps={[]} />);
    expect(screen.getByText("No steps yet.")).toBeInTheDocument();
  });

  it("lists the steps in order, numbered from 1", () => {
    render(<StepTimeline steps={STEPS} />);
    expect(screen.getAllByText(/^Step \d$/).map((el) => el.textContent)).toEqual([
      "Step 1",
      "Step 2",
      "Step 3",
    ]);
    expect(within(item(1)).getByText("Model call")).toBeInTheDocument();
    expect(within(item(2)).getByText("Tool call")).toBeInTheDocument();
    expect(within(item(2)).getByText("utility.calculate")).toBeInTheDocument();
  });

  it("summarizes what a model call did without opening anything", () => {
    render(<StepTimeline steps={STEPS} />);
    expect(within(item(1)).getByText("Asked to use: utility_calculate")).toBeInTheDocument();
    expect(within(item(3)).getByText("VAT is KES 2,000.")).toBeInTheDocument();
  });

  it("shows duration and tokens", () => {
    render(<StepTimeline steps={STEPS} />);
    expect(within(item(1)).getByText("1.0 s · 340 tokens")).toBeInTheDocument();
    expect(within(item(2)).getByText("1.0 s")).toBeInTheDocument();
  });

  it("keeps inputs and outputs behind a details toggle", () => {
    render(<StepTimeline steps={STEPS} />);
    const tool = item(2);
    const details = tool.querySelector("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(tool).getByText("Details")).toBeInTheDocument();
    expect(tool.textContent).toContain('"expression": "12500 * 0.16"');
    expect(tool.textContent).toContain('"result": 2000');
  });

  it("shows a failed or skipped step's reason prominently", () => {
    render(
      <StepTimeline
        steps={[
          step(0, {
            step_type: "tool_call",
            tool_key: "utility.calculate",
            status: "failed",
            error: "Invalid arguments. expression: 5 is not of type 'string'",
            output: null,
          }),
          step(1, {
            step_type: "tool_call",
            tool_key: "slack.send_message",
            status: "skipped",
            error:
              "This action needs a person's approval, and approvals are not available yet, so it was not run.",
            output: null,
          }),
        ]}
      />,
    );
    expect(within(item(1)).getByText("Failed")).toBeInTheDocument();
    expect(within(item(1)).getByRole("alert")).toHaveTextContent("Invalid arguments.");
    expect(within(item(2)).getByText("Skipped")).toBeInTheDocument();
    expect(within(item(2)).getByRole("alert")).toHaveTextContent("approvals are not available yet");
  });

  it("shortens a long reply in the summary", () => {
    const long = "word ".repeat(100).trim();
    render(<StepTimeline steps={[step(0, { output: { text: long, tool_calls: [] } })]} />);
    const summary = item(1).querySelector("p") as HTMLElement;
    expect(summary.textContent?.length).toBeLessThan(170);
    expect(summary.textContent?.endsWith("…")).toBe(true);
  });

  it("copes with a step that is still running", () => {
    render(
      <StepTimeline
        steps={[step(0, { status: "running", finished_at: null, input: null, output: null })]}
      />,
    );
    expect(within(item(1)).getByText("Running")).toBeInTheDocument();
    expect(item(1).querySelector("details")).toBeNull();
  });
});
