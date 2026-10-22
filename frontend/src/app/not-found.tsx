import Link from "next/link";

export default function NotFound() {
  return (
    <div
      className="flex min-h-screen items-center justify-center px-4"
      style={{ backgroundColor: "var(--color-surface)" }}
    >
      <div className="w-full text-center" style={{ maxWidth: "30rem" }}>
        <p
          className="text-body-sm font-medium"
          style={{ color: "var(--color-brand)", letterSpacing: "0.05em" }}
        >
          404
        </p>
        <h1
          className="mt-3 text-h1"
          style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
        >
          That page is not here
        </h1>
        <p
          className="mt-3 text-body"
          style={{ color: "var(--color-text-secondary)", maxWidth: "44ch", margin: "0 auto" }}
        >
          The link may be out of date, or the page may have moved. The dashboard is the place to
          start.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/dashboard" className="btn btn-primary">
            Go to the dashboard
          </Link>
          <Link href="/" className="btn btn-secondary">
            Home
          </Link>
        </div>
      </div>
    </div>
  );
}
