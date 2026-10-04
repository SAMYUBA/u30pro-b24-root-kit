#include "u30_guard.h"
#include <assert.h>
int main(int argc,char **argv){
 assert(argc>3);const char *test=argv[1];argv[1]=argv[0];argc--;argv++;
 assert(!u30_wire_allowed(1)&&!u30_wire_allowed(2)&&!u30_wire_allowed(3)&&!u30_wire_allowed(5));
 if(!strcmp(test,"bad-cli")){assert(!u30_validate_cli(argc,argv));return 0;}
 assert(u30_validate_cli(argc,argv));
 if(!strcmp(test,"write")){u30_perform_write(NULL);return 90;}
 u30_verify_set(argv[11],1);assert(u30_wire_allowed(5));
 assert(!u30_wire_allowed(1)&&!u30_wire_allowed(2)&&!u30_wire_allowed(3));
 if(!strcmp(test,"repeat"))u30_verify_set(argv[11],1);
 return 0;
}
