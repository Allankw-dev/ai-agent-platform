import Link from "next/link";
import {
  Activity,
  Bot,
  Gauge,
  Layers,
  Plug,
  ShieldCheck,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const features: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: Bot,
    title: "Versioned agents",
    body: "Write instructions, pick a Claude model and set limits. Every change is a version you can roll back.",
  },
  {
    icon: Plug,
    title: "Controlled tools",
    body: "Agents only get the tools you grant: HTTP APIs, Slack, GitHub and Gmail. Every call is validated before it runs.",
  },
  {
    icon: UserCheck,
    title: "Human approvals",
    body: "Sending messages, deleting data or changing resources can pause for a person to approve or reject.",
  },
  {
    icon: Activity,
    title: "Full execution history",
    body: "Inspect each step, tool call, error and duration of every run, and retry the ones that failed.",
  },
  {
    icon: Layers,
    title: "Organization isolation",
    body: "Teams share a platform but never each other's data, enforced in the app and in the database.",
  },
  {
    icon: Gauge,
    title: "Usage and cost tracking",
    body: "See tokens and estimated cost per run and per agent, with limits that stop runaway executions.",
  },
];

const steps = [
  { title: "Define an agent", body: "Give it instructions, a model and a set of allowed tools." },
  { title: "Run a task", body: "Start it manually or from the playground." },
  {
    title: "The agent works in a loop",
    body: "Claude asks to use a tool; the platform validates the request, checks permissions and runs it.",
  },
  {
    title: "Approve what matters",
    body: "Sensitive actions pause the run until a person decides.",
  },
  { title: "Review the result", body: "Every step, token and cost is recorded for inspection." },
];

const principles = [
  "Organization data is isolated in the application and again in the database.",
  "Model-generated tool arguments are never trusted; they are validated against each tool's schema.",
  "No AI-generated code or shell commands are ever executed.",
  "Integration credentials are encrypted and never returned by the API.",
];

export default function Home() {
  return (
    <>
      <section className="bg-[radial-gradient(ellipse_at_top,rgba(124,92,255,0.2),transparent_60%)]">
        <div className="mx-auto max-w-6xl px-6 py-24 text-center sm:py-32">
          <Badge variant="accent" className="mb-6">
            In development
          </Badge>
          <h1 className="mx-auto max-w-3xl text-4xl font-semibold tracking-tight sm:text-6xl">
            AI agents that do real work, under your control
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            Build agents on Claude, connect the tools your team already uses, and approve the
            actions that matter. Every step is validated, permissioned and logged.
          </p>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Link href="/register" className={buttonVariants({ size: "lg" })}>
              Get started
            </Link>
            <Link
              href="/#how-it-works"
              className={buttonVariants({ size: "lg", variant: "outline" })}
            >
              See how it works
            </Link>
          </div>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-20">
        <h2 className="text-3xl font-semibold tracking-tight">Built for real operations</h2>
        <p className="mt-3 max-w-2xl text-muted-foreground">
          Not a chatbot. A platform for agents that act on your systems, with the controls a
          business needs.
        </p>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map(({ icon: Icon, title, body }) => (
            <Card key={title}>
              <CardHeader>
                <Icon aria-hidden className="mb-2 size-6 text-accent" />
                <CardTitle>{title}</CardTitle>
                <CardDescription>{body}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      <section id="how-it-works" className="scroll-mt-20 border-y border-border/60 bg-card/40">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-3xl font-semibold tracking-tight">How it works</h2>
          <ol className="mt-10 grid gap-6 md:grid-cols-5">
            {steps.map((step, index) => (
              <li key={step.title} className="relative">
                <span
                  className={cn(
                    "mb-3 grid size-8 place-items-center rounded-full border border-primary/50",
                    "bg-primary/15 text-sm font-semibold",
                  )}
                >
                  {index + 1}
                </span>
                <h3 className="font-medium">{step.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="security" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-20">
        <div className="flex items-center gap-3">
          <ShieldCheck aria-hidden className="size-7 text-accent" />
          <h2 className="text-3xl font-semibold tracking-tight">Designed for least privilege</h2>
        </div>
        <p className="mt-3 max-w-2xl text-muted-foreground">
          These are the commitments the platform is being built against.
        </p>
        <ul className="mt-8 grid gap-3 md:grid-cols-2">
          {principles.map((principle) => (
            <li
              key={principle}
              className="rounded-lg border border-border bg-card px-5 py-4 text-sm"
            >
              {principle}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
