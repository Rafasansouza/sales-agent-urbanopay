-- =============================================================================
-- Extensões do PostgreSQL — UrbanoPay Mobilidade
-- =============================================================================
-- Executado apenas na primeira criação do volume de dados.
--
-- Fonte: ADR-004.
--
-- Este script cria somente extensões. Nenhuma tabela, nenhum schema de domínio
-- e nenhum seed: o esquema pertence a migrations versionadas com Alembic
-- (ADR-012, aceito), que ainda não foram materializadas.
-- =============================================================================

-- pgvector: restrito a recuperação semântica de FAQ, descrições e conteúdo
-- textual. Nunca autoritativo para preço, saldo ou status de pagamento.
CREATE EXTENSION IF NOT EXISTS vector;

-- Geração de UUID no banco, para IDs opacos (ADR-006).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Índice GiST/GIN com operadores de igualdade: necessário para constraints de
-- exclusão que garantam invariantes como "no máximo um Payment APPROVED por
-- Order" (ADR-007, SPEC-003 §13).
CREATE EXTENSION IF NOT EXISTS btree_gist;
