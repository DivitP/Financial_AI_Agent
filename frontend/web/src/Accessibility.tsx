import { ReactNode, useEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";

export function Navigation() {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <nav aria-label="Primary navigation">
        <NavLink to="/" end className="brand">
          Financial AI <span>Research</span>
        </NavLink>
        <div className="nav-links">
          {[
            ["/history", "Saved research"],
            ["/watchlists", "Watchlists"],
            ["/calendar", "Calendar"],
            ["/compare", "Compare"],
            ["/portfolio", "Portfolio context"],
            ["/settings", "Settings"],
          ].map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
          <a href="/docs">API docs</a>
        </div>
      </nav>
    </>
  );
}

/** Announce client-side navigation without stealing focus on data refreshes. */
export function RouteAccessibility() {
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  useEffect(() => {
    let focusPending = previous.current !== pathname;
    let focusedMain: HTMLElement | null = null;
    previous.current = pathname;
    const update = () => {
      const main = document.querySelector<HTMLElement>("main");
      const heading = main?.querySelector<HTMLElement>("h1");
      document.title = `${heading?.textContent ?? "Research"} · Financial AI`;
      const replacedLoadingMain =
        focusedMain && !focusedMain.isConnected && document.activeElement === document.body;
      if ((focusPending || replacedLoadingMain) && main) {
        // Focus the landmark immediately, including loading/error routes.
        main.focus();
        focusedMain = main;
        focusPending = false;
      }
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.getElementById("root") ?? document.body, {
      childList: true,
      subtree: true,
    });
    return () => observer.disconnect();
  }, [pathname]);
  return null;
}

export function EvidenceDialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // jsdom has no dialog implementation; browsers use native modal inertness.
    if (element.showModal) element.showModal();
    else element.setAttribute("open", "");
    element.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      if (element.close) element.close();
      document.body.style.overflow = overflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="drawer"
      aria-label={title}
      aria-modal="true"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
        if (e.key !== "Tab") return;
        const controls = [
          ...e.currentTarget.querySelectorAll<HTMLElement>(
            'a[href], button:not(:disabled), [tabindex="0"]',
          ),
        ];
        const first = controls[0],
          last = controls.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }}
    >
      <button className="secondary close" onClick={onClose}>
        Close
      </button>
      <h2>{title}</h2>
      {children}
    </dialog>
  );
}
