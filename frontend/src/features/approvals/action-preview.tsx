import { Badge } from "@/components/ui/badge";
import { headerPairs } from "@/features/approvals/approval-format";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[8rem_1fr] sm:gap-3">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  );
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : JSON.stringify(value);
}

function SlackPreview({ input }: { input: Record<string, unknown> }) {
  return (
    <>
      <dl className="space-y-3">
        <Row label="Channel">
          <code className="break-all font-mono text-xs">{str(input.channel)}</code>
        </Row>
        <Row label="Message">
          <p className="whitespace-pre-wrap break-words rounded-lg border border-border bg-background p-3">
            {str(input.text)}
          </p>
        </Row>
      </dl>
      <p className="text-xs text-muted-foreground">
        This is the final text. Mentions such as @channel are disabled, and link previews are off.
      </p>
    </>
  );
}

function HttpPreview({ input }: { input: Record<string, unknown> }) {
  const headers = headerPairs(input.headers);
  const body = str(input.body);
  return (
    <>
      <dl className="space-y-3">
        <Row label="Method">
          <Badge variant="danger">{str(input.method)}</Badge>
        </Row>
        <Row label="URL">
          {/* Shown as text on purpose, never as a link: nobody should open it by accident. */}
          <code className="break-all font-mono text-xs">{str(input.url)}</code>
        </Row>
        {headers.length > 0 && (
          <Row label="Headers">
            <ul className="space-y-1">
              {headers.map((header) => (
                <li key={header.name} className="break-all font-mono text-xs">
                  {header.name}: {header.value}
                </li>
              ))}
            </ul>
          </Row>
        )}
        {body !== "" && (
          <Row label={input.content_type ? `Body (${str(input.content_type)})` : "Body"}>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-background p-3 font-mono text-xs">
              {body}
            </pre>
          </Row>
        )}
      </dl>
      <p className="text-xs text-muted-foreground">
        The platform adds the integration&apos;s saved credential when this runs. You do not see it
        here, and the agent never does.
      </p>
    </>
  );
}

/**
 * What will run if this is approved, in plain words for the tools people approve most, followed
 * by the exact data for every tool. The data is the real arguments, so what is on screen is what
 * runs. Everything is shown as text; nothing from the agent is ever rendered as markup.
 */
export function ActionPreview({
  toolKey,
  input,
}: {
  toolKey: string;
  input: Record<string, unknown>;
}) {
  return (
    <div className="space-y-4">
      {toolKey === "slack.send_message" && <SlackPreview input={input} />}
      {toolKey === "http.request" && <HttpPreview input={input} />}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
          Exact data
        </summary>
        <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-border bg-background p-3 font-mono text-xs">
          {JSON.stringify(input, null, 2)}
        </pre>
      </details>
    </div>
  );
}
