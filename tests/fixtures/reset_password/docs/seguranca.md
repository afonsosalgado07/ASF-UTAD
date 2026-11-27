# Notas de segurança da equipa

- Os tokens enviados por e-mail devem ser aleatórios (módulo `secrets`) e guardados só como hash.
- O endpoint legado `/reset-password` tem dois problemas conhecidos: revela se um e-mail está registado
  e envia uma password temporária em claro, sem prazo. Continua ativo porque a app móvel antiga o usa.
- Qualquer alteração ao módulo `auth` passa por revisão de segurança antes de ir para produção.
