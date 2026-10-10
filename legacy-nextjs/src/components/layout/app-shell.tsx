"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, LogOut, Menu, UserRound, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { can, type PermissionSet } from "@/lib/permissions";
import { ROLE_LABELS, type Role } from "@/lib/constants";
import { Avatar } from "@/components/ui/misc";
import { logoutAction } from "@/app/login/actions";
import type { NavSection } from "./nav-config";
import { PANEL_NAV, SUPER_NAV } from "./nav-config";
import { Logo } from "./logo";

export interface ShellUser {
  name: string;
  email: string;
  role: Role;
  permissions: PermissionSet;
}

export interface ShellCampaign {
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  primaryColor: string;
  logoUrl: string | null;
}

function visibleSections(sections: NavSection[], user: ShellUser): NavSection[] {
  return sections
    .map((s) => ({
      ...s,
      items: s.items.filter((item) => {
        if (item.adminOnly) return user.role === "ADMIN";
        if (item.module) return can(user.permissions, item.module, "view");
        return true;
      }),
    }))
    .filter((s) => s.items.length > 0);
}

function isActive(pathname: string, href: string, exact?: boolean) {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({
  user,
  campaign,
  variant,
  children,
}: {
  user: ShellUser;
  campaign?: ShellCampaign | null;
  variant: "panel" | "super";
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const sections = visibleSections(variant === "super" ? SUPER_NAV : PANEL_NAV, user);
  const profileHref = variant === "super" ? "/super/perfil" : "/painel/perfil";

  React.useEffect(() => setMobileOpen(false), [pathname]);

  const sidebar = (
    <div className="flex h-full flex-col bg-slate-900 text-slate-300">
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-white/10 px-5">
        <Logo className="text-white" />
        {variant === "super" && (
          <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-amber-300 uppercase">
            Super
          </span>
        )}
      </div>

      {campaign && (
        <div className="mx-3 mt-4 flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2.5">
          {campaign.logoUrl ? (
            <img src={campaign.logoUrl} alt="" className="size-9 shrink-0 rounded-md bg-white object-contain" />
          ) : (
            <span
              className="flex size-9 shrink-0 items-center justify-center rounded-md text-sm font-bold text-white"
              style={{ backgroundColor: campaign.primaryColor }}
            >
              {campaign.ballotNumber?.slice(0, 2) || campaign.ballotName.slice(0, 1)}
            </span>
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">{campaign.ballotName}</p>
            <p className="truncate text-xs text-slate-400">
              {[campaign.ballotNumber, campaign.party].filter(Boolean).join(" · ") || "Campanha"}
            </p>
          </div>
        </div>
      )}

      <nav className="mt-4 flex-1 space-y-6 overflow-y-auto px-3 pb-6 scrollbar-thin" aria-label="Menu principal">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="px-3 pb-2 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">{section.title}</p>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = isActive(pathname, item.href, item.exact);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                        active ? "bg-brand-600 text-white shadow-sm" : "text-slate-300 hover:bg-white/5 hover:text-white",
                      )}
                    >
                      <Icon className="size-4.5 shrink-0" aria-hidden />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/10 p-3 text-[11px] text-slate-500">
        Dados tratados conforme a LGPD · <span className="text-slate-400">efind.com.br</span>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen">
      {/* Sidebar desktop */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 lg:block">{sidebar}</aside>

      {/* Sidebar mobile */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/60" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-xl">
            {sidebar}
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className="absolute top-4 right-3 rounded-md p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
              aria-label="Fechar menu"
            >
              <X className="size-5" />
            </button>
          </aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-6">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-2 text-slate-500 hover:bg-slate-100 lg:hidden"
            aria-label="Abrir menu"
          >
            <Menu className="size-5" />
          </button>
          <div className="lg:hidden">
            <Logo />
          </div>
          <div className="flex-1" />
          <UserMenu user={user} profileHref={profileHref} />
        </header>
        <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

function UserMenu({ user, profileHref }: { user: ShellUser; profileHref: string }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-100"
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <Avatar name={user.name} />
        <span className="hidden text-left sm:block">
          <span className="block max-w-40 truncate text-sm font-medium text-slate-900">{user.name}</span>
          <span className="block text-xs text-slate-500">{ROLE_LABELS[user.role]}</span>
        </span>
        <ChevronDown className="size-4 text-slate-400" />
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-60 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg" role="menu">
          <div className="px-3 py-2">
            <p className="truncate text-sm font-medium text-slate-900">{user.name}</p>
            <p className="truncate text-xs text-slate-500">{user.email}</p>
          </div>
          <div className="my-1 h-px bg-slate-100" />
          <Link
            href={profileHref}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            role="menuitem"
            onClick={() => setOpen(false)}
          >
            <UserRound className="size-4" /> Meu perfil
          </Link>
          <form action={logoutAction}>
            <button type="submit" className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50" role="menuitem">
              <LogOut className="size-4" /> Sair
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
