// Gera um cookie de sessão para testes locais com curl (somente desenvolvimento).
// Uso: npm run dev:token -- admin@demo.efind.com.br
//      curl -s -b "efind_session=<token>" http://localhost:3000/painel
import { PrismaClient } from "@prisma/client";
import { signSession } from "../src/lib/session";

async function main() {
  if (process.env.NODE_ENV === "production") throw new Error("Não use em produção");
  const email = process.argv[2];
  if (!email) throw new Error("Informe o e-mail: npm run dev:token -- email@exemplo.com");
  const prisma = new PrismaClient();
  const user = await prisma.user.findUnique({ where: { email: email.toLowerCase() } });
  await prisma.$disconnect();
  if (!user) throw new Error(`Usuário ${email} não encontrado`);
  process.stdout.write(await signSession({ sub: user.id, sv: user.sessionVersion }));
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
