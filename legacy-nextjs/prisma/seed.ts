// Seed de desenvolvimento: super admin + campanha de demonstração com equipe e eleitores fictícios.
// Idempotente: não duplica se já existir. Uso: npm run db:seed
import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";
import { bootstrapCampaign } from "../src/server/campaign/bootstrap";
import { encryptJson, randomInviteCode, randomToken } from "../src/lib/crypto";
import { serializeTags } from "../src/lib/utils";

const prisma = new PrismaClient();

const DEMO_PASSWORD = "Demo@2026";

// Bairros de Campinas/SP com coordenadas aproximadas (centro do bairro)
const BAIRROS = [
  { nome: "Centro", lat: -22.9056, lng: -47.0608, cep: "13010" },
  { nome: "Cambuí", lat: -22.8937, lng: -47.0508, cep: "13024" },
  { nome: "Taquaral", lat: -22.8735, lng: -47.0544, cep: "13076" },
  { nome: "Barão Geraldo", lat: -22.8166, lng: -47.0846, cep: "13084" },
  { nome: "Sousas", lat: -22.8806, lng: -46.9706, cep: "13105" },
  { nome: "Jardim Proença", lat: -22.9137, lng: -47.0469, cep: "13026" },
  { nome: "Botafogo", lat: -22.8996, lng: -47.0707, cep: "13020" },
  { nome: "Vila Industrial", lat: -22.9175, lng: -47.0744, cep: "13035" },
  { nome: "Campos Elíseos", lat: -22.9275, lng: -47.0931, cep: "13060" },
  { nome: "Jardim do Lago", lat: -22.9318, lng: -47.1025, cep: "13050" },
  { nome: "Ouro Verde", lat: -22.9839, lng: -47.1305, cep: "13056" },
  { nome: "Nova Campinas", lat: -22.8972, lng: -47.0425, cep: "13092" },
];

const NOMES = ["Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique", "Isabela", "João", "Larissa", "Marcos", "Natália", "Otávio", "Paula", "Rafael", "Sabrina", "Thiago", "Vanessa", "Wagner", "Yasmin", "Lucas", "Mariana", "Pedro", "Beatriz", "Gustavo", "Camila", "Rodrigo", "Juliana", "André"];
const SOBRENOMES = ["Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa", "Ferreira", "Almeida", "Ribeiro", "Carvalho", "Gomes", "Martins", "Araújo", "Barbosa", "Rocha"];
const RUAS = ["Rua das Flores", "Av. Brasil", "Rua José Paulino", "Rua Barão de Jaguara", "Av. Norte-Sul", "Rua Coronel Quirino", "Rua Maria Monteiro", "Av. Orosimbo Maia"];
const APOIO = ["APOIADOR", "APOIADOR", "SIMPATIZANTE", "SIMPATIZANTE", "INDECISO", null];
const TAGS = ["saude", "educacao", "jovem", "idoso", "comerciante", "igreja", "esporte"];

// PRNG determinístico (seed reproduzível)
let s = 42;
const rand = () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
const pick = <T,>(arr: T[]) => arr[Math.floor(rand() * arr.length)];

async function main() {
  const superEmail = (process.env.SEED_SUPERADMIN_EMAIL ?? "super@efind.com.br").toLowerCase();
  const superPassword = process.env.SEED_SUPERADMIN_PASSWORD;
  if (!superPassword) throw new Error("Defina SEED_SUPERADMIN_PASSWORD no .env");

  const existingSuper = await prisma.user.findUnique({ where: { email: superEmail } });
  if (!existingSuper) {
    await prisma.user.create({
      data: {
        name: "Super Admin E-Find",
        email: superEmail,
        passwordHash: await bcrypt.hash(superPassword, 12),
        role: "SUPER_ADMIN",
        inviteCode: randomInviteCode(10),
      },
    });
    console.log(`✔ Super admin criado: ${superEmail}`);
  }

  if (await prisma.campaign.findUnique({ where: { slug: "demo" } })) {
    console.log("• Campanha demo já existe — nada a fazer.");
    return;
  }

  const hash = await bcrypt.hash(DEMO_PASSWORD, 12);

  await prisma.$transaction(
    async (tx) => {
      const campaign = await tx.campaign.create({
        data: {
          slug: "demo",
          candidateName: "João Carlos Demonstração",
          ballotName: "Dr. João Demo",
          ballotNumber: "12345",
          party: "PDEMO",
          office: "VEREADOR",
          city: "Campinas",
          state: "SP",
          electionYear: 2026,
          primaryColor: "#4f46e5",
          voterGoal: 5000,
          formTitle: "Faça parte da nossa campanha!",
          formMessage: "Cadastre-se para receber novidades e participar das ações no seu bairro.",
          privacyContact: "privacidade@demo.efind.com.br",
        },
      });
      await bootstrapCampaign(tx, campaign.id);

      const admin = await tx.user.create({
        data: { campaignId: campaign.id, name: "Admin Demo", email: "admin@demo.efind.com.br", passwordHash: hash, role: "ADMIN", inviteCode: randomInviteCode() },
      });
      const coords = [];
      for (const [i, nome] of ["Coordenadora Fernanda", "Coordenador Ricardo"].entries()) {
        coords.push(
          await tx.user.create({
            data: {
              campaignId: campaign.id,
              name: nome,
              email: `coord${i + 1}@demo.efind.com.br`,
              passwordHash: hash,
              role: "COORDENADOR",
              parentId: admin.id,
              inviteCode: randomInviteCode(),
              goal: 800,
              region: i === 0 ? "Região Norte" : "Região Sul",
            },
          }),
        );
      }
      const cabos = [];
      const caboNomes = ["Cabo Paulo", "Cabo Renata", "Cabo Sérgio", "Cabo Tatiane", "Cabo Valter"];
      for (const [i, nome] of caboNomes.entries()) {
        cabos.push(
          await tx.user.create({
            data: {
              campaignId: campaign.id,
              name: nome,
              email: `cabo${i + 1}@demo.efind.com.br`,
              phone: `55199${String(81000000 + i * 1111).padStart(8, "0")}`,
              passwordHash: hash,
              role: "CABO",
              parentId: coords[i % 2].id,
              inviteCode: randomInviteCode(),
              goal: 150,
            },
          }),
        );
      }

      const registrars = [...cabos, ...cabos, ...cabos, ...coords, admin];
      const used = new Set<string>();
      const now = Date.now();
      for (let i = 0; i < 240; i++) {
        const b = pick(BAIRROS);
        const name = `${pick(NOMES)} ${pick(SOBRENOMES)} ${pick(SOBRENOMES)}`;
        let phone: string;
        do phone = `55199${String(Math.floor(rand() * 1e8)).padStart(8, "0")}`;
        while (used.has(phone));
        used.add(phone);
        const createdAt = new Date(now - Math.floor(rand() * 45) * 86400000 - Math.floor(rand() * 86400000));
        const optIn = rand() > 0.15;
        const tagCount = Math.floor(rand() * 3);
        await tx.voter.create({
          data: {
            campaignId: campaign.id,
            registeredById: pick(registrars).id,
            name,
            phone,
            email: rand() > 0.6 ? `${name.split(" ")[0].toLowerCase()}${i}@exemplo.com` : null,
            birthDate: new Date(1950 + Math.floor(rand() * 56), Math.floor(rand() * 12), 1 + Math.floor(rand() * 28)),
            gender: pick(["M", "F", "F", "M", "N"]),
            cep: `${b.cep}${String(Math.floor(rand() * 999)).padStart(3, "0")}`,
            street: pick(RUAS),
            number: String(1 + Math.floor(rand() * 1500)),
            neighborhood: b.nome,
            city: "Campinas",
            state: "SP",
            latitude: b.lat + (rand() - 0.5) * 0.012,
            longitude: b.lng + (rand() - 0.5) * 0.012,
            geoStatus: "OK",
            supportLevel: pick(APOIO),
            tags: serializeTags(Array.from({ length: tagCount }, () => pick(TAGS))),
            source: pick(["LINK", "QRCODE", "QRCODE", "MANUAL"]),
            consentAt: createdAt,
            consentIp: "127.0.0.1",
            whatsappOptIn: optIn,
            optOutAt: optIn && rand() > 0.95 ? createdAt : null,
            createdAt,
          },
        });
      }

      await tx.whatsAppConnection.create({
        data: {
          campaignId: campaign.id,
          name: "Simulador (testes)",
          provider: "SANDBOX",
          status: "CONNECTED",
          phoneNumber: "+55 19 90000-0000",
          credentials: encryptJson({ failureRate: "0.05" }),
          webhookToken: randomToken(),
          isDefault: true,
          ratePerMinute: 60,
        },
      });

      await tx.messageTemplate.createMany({
        data: [
          {
            campaignId: campaign.id,
            createdById: admin.id,
            name: "Boas-vindas",
            category: "BOAS_VINDAS",
            body: "Olá, {{primeiro_nome}}! 👋 Obrigado por se cadastrar na campanha de {{candidato}} ({{numero}}). Vamos juntos fazer mais pelo {{bairro}}! Para não receber mais mensagens, responda SAIR.",
          },
          {
            campaignId: campaign.id,
            createdById: admin.id,
            name: "Convite para reunião no bairro",
            category: "CONVITE",
            body: "{{primeiro_nome}}, vamos ter um encontro com {{candidato}} no {{bairro}} neste sábado às 10h. Sua presença é muito importante! Responda SAIR para não receber mais mensagens.",
          },
        ],
      });
    },
    { timeout: 120_000 },
  );

  console.log("✔ Campanha demo criada");
  console.log(`  admin@demo.efind.com.br / coord1@demo.efind.com.br / cabo1@demo.efind.com.br  — senha: ${DEMO_PASSWORD}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
