#pragma once
#include "common.h"
int u30_wire_allowed(int type);
int u30_command_arity(int count,char **args,int synthetic,int fdl1,int fdl2);
int u30_validate_cli(int argc,char **argv);
void u30_verify_set(const char *directory,int after);
void u30_perform_write(spdio_t *io);
