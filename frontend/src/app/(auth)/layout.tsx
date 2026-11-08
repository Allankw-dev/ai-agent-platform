import Link from "next/link";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col bg-[radial-gradient(ellipse_at_top,rgba(124,92,255,0.15),transparent_60%)]">
      <header className="mx-auto flex h-16 w-full max-w-6xl items-center px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span
            aria-hidden
            className="grid size-7 place-items-center rounded-md bg-gradient-to-br from-primary to-accent text-xs font-bold text-background"
          >
            A
          </span>
          Agent Platform
        </Link>
      </header>
      <main className="grid flex-1 place-items-center px-6 pb-16">{children}</main>
    </div>
  );
}
