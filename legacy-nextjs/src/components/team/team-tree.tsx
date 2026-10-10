"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/misc";
import { cn, formatNumber } from "@/lib/utils";
import { GoalMeter } from "./goal-meter";
import { RoleBadge, StatusBadge } from "./role-badge";
import { buildTeamTree, collectParentIds, type TeamTreeNode } from "./team-logic";
import type { TeamMemberDTO } from "./types";

/** Árvore recolhível admin → coordenadores → cabos */
export function TeamTree({ members }: { members: TeamMemberDTO[] }) {
  const tree = React.useMemo(() => buildTeamTree(members), [members]);
  const parentIds = React.useMemo(() => collectParentIds(tree), [tree]);
  const [expanded, setExpanded] = React.useState<Set<string>>(() => {
    // Equipes pequenas abrem inteiras; nas grandes só o primeiro nível
    if (members.length <= 40) return new Set(parentIds);
    return new Set(tree.filter((n) => n.children.length).map((n) => n.member.id));
  });

  const toggle = React.useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const allOpen = parentIds.length > 0 && parentIds.every((id) => expanded.has(id));

  return (
    <div>
      {parentIds.length > 0 && (
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2 sm:px-5">
          <p className="text-xs text-slate-500">Clique no nome para ver o perfil e o desempenho do membro.</p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(allOpen ? new Set() : new Set(parentIds))}
            aria-label={allOpen ? "Recolher todos" : "Expandir todos"}
          >
            {allOpen ? <ChevronsDownUp aria-hidden /> : <ChevronsUpDown aria-hidden />}
            <span className="hidden sm:inline">{allOpen ? "Recolher tudo" : "Expandir tudo"}</span>
          </Button>
        </div>
      )}
      <ul role="tree" aria-label="Hierarquia da equipe" className="space-y-0.5 p-2 sm:p-3">
        {tree.map((node) => (
          <TreeItem key={node.member.id} node={node} expanded={expanded} onToggle={toggle} />
        ))}
      </ul>
    </div>
  );
}

function TreeItem({
  node,
  expanded,
  onToggle,
}: {
  node: TeamTreeNode;
  expanded: Set<string>;
  onToggle: (id: string) => void;
}) {
  const m = node.member;
  const hasChildren = node.children.length > 0;
  const open = hasChildren && expanded.has(m.id);
  const groupId = `tree-${m.id}`;

  return (
    <li role="treeitem" aria-expanded={hasChildren ? open : undefined} aria-selected={false}>
      <div className={cn("flex items-start gap-2 rounded-lg px-1.5 py-2 hover:bg-slate-50 sm:px-2", !m.active && "opacity-60")}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(m.id)}
            aria-controls={groupId}
            aria-label={open ? `Recolher equipe de ${m.name}` : `Expandir equipe de ${m.name}`}
            className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-800"
          >
            {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
          </button>
        ) : (
          <span className="size-6 shrink-0" aria-hidden />
        )}
        <Avatar name={m.name} className="mt-0.5 hidden sm:inline-flex" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Link
              href={`/painel/equipe/${m.id}`}
              className="max-w-full truncate text-sm font-semibold text-slate-900 hover:text-brand-700 hover:underline"
            >
              {m.name}
            </Link>
            <RoleBadge role={m.role} />
            <StatusBadge active={m.active} />
            {m.isSelf && <Badge tone="brand">Você</Badge>}
            {node.detached && <Badge tone="yellow">Sem responsável</Badge>}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-slate-500">
            <span>
              <strong className="font-semibold text-slate-800 tabular-nums">{formatNumber(m.votersTotal)}</strong>{" "}
              {m.votersTotal === 1 ? "eleitor" : "eleitores"}
              {m.voters7d > 0 && <span className="text-emerald-600"> · +{formatNumber(m.voters7d)} em 7 dias</span>}
            </span>
            {hasChildren && (
              <span>
                Rede: <strong className="font-semibold text-slate-800 tabular-nums">{formatNumber(node.networkTotal)}</strong> ·{" "}
                {node.size - 1} {node.size - 1 === 1 ? "membro" : "membros"}
              </span>
            )}
            <GoalMeter total={m.votersTotal} goal={m.goal} />
          </div>
        </div>
      </div>
      {open && (
        <ul id={groupId} role="group" className="ml-4 space-y-0.5 border-l border-slate-200 pl-1.5 sm:ml-5 sm:pl-3">
          {node.children.map((child) => (
            <TreeItem key={child.member.id} node={child} expanded={expanded} onToggle={onToggle} />
          ))}
        </ul>
      )}
    </li>
  );
}
