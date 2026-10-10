"use client";

import * as React from "react";
import { Button, type ButtonVariant } from "@/components/ui/button";
import { Modal } from "@/components/ui/client";

/** Confirmação em modal para ações sensíveis (desativar, novo link, redefinir senha...) */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  children,
  confirmLabel,
  confirmVariant = "primary",
  pending,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  confirmLabel: React.ReactNode;
  confirmVariant?: ButtonVariant;
  pending?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={pending ? () => undefined : onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            Cancelar
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm} loading={pending}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Modal>
  );
}
