export function EmptyState({ children }: { children: string }) { return <div className="terra-empty">{children}</div>; }

export function PageIntro({ label, title, children }: { label: string; title: string; children: string }) { return <section className="terra-intro"><p>{label}</p><h1>{title}</h1><span>{children}</span></section>; }
