#include "u30_guard.h"
#include PROFILE_HEADER
#include <assert.h>
int selected_ab=2;
static int opcode,start_count,end_count,mode;
static size_t offset;
static unsigned char *expected;
void encode_msg_nocpy(spdio_t *io,int type,size_t n){
 assert(u30_wire_allowed(type));opcode=type;
 if(type==1){assert(++start_count==1&&n==76);assert(READ32_LE(io->temp_buf+72)==candidate_size);for(size_t i=0;i<strlen(write_target);i++)assert(io->temp_buf[i*2]==write_target[i]&&io->temp_buf[i*2+1]==0);}
 if(type==2){assert(start_count==1&&!end_count&&n<=0xf800&&offset+n<=candidate_size);assert(!memcmp(io->temp_buf,expected+offset,n));offset+=n;}
 if(type==3){assert(++end_count==1&&offset==candidate_size&&n==0);}
}
int send_and_check(spdio_t *io){(void)io;if((mode==1&&opcode==1)||(mode==2&&opcode==2)||(mode==3&&opcode==3))return 1;return 0;}
int main(int argc,char **argv){
 assert(argc>3);const char *test=argv[1];argv[1]=argv[0];argc--;argv++;
 if(!strcmp(test,"start-fail"))mode=1;if(!strcmp(test,"data-fail"))mode=2;if(!strcmp(test,"end-fail"))mode=3;
 assert(!u30_wire_allowed(1)&&!u30_wire_allowed(2)&&!u30_wire_allowed(3)&&!u30_wire_allowed(5));
 if(!strcmp(test,"bad-cli")){assert(!u30_validate_cli(argc,argv));puts("PASS: bad CLI rejected before USB");return 0;}
 assert(u30_validate_cli(argc,argv));const char *dir=argv[11];
 spdio_t io={0};unsigned char buf[65536];partition_t part={0};strcpy(part.name,write_target);part.size=candidate_size;io.ptable=&part;io.part_count=1;io.temp_buf=buf;io.timeout=1000;
 expected=malloc(candidate_size);FILE *file=fopen(candidate_path,"rb");assert(file&&fread(expected,1,candidate_size,file)==candidate_size);fclose(file);
 if(!strcmp(test,"freeze")){FILE *changed=fopen(candidate_path,"wb");assert(changed);assert(fwrite("changed after validation",1,24,changed)==24);assert(!fclose(changed));}
 if(!strcmp(test,"write-before-check")){u30_perform_write(&io);return 90;}
 if(!strcmp(test,"before-mismatch")){u30_verify_set("/private/tmp/no-such-trial-inputs",0);return 90;}
 u30_verify_set(dir,0);assert(!u30_wire_allowed(1)&&!u30_wire_allowed(5));
 if(!strcmp(test,"wrong-slot"))selected_ab=1;
 if(!strcmp(test,"wrong-size"))part.size--;
 u30_perform_write(&io);
 assert(start_count==1&&end_count==1&&offset==candidate_size);assert(!u30_wire_allowed(1)&&!u30_wire_allowed(5));
 if(!strcmp(test,"repeat-write")){u30_perform_write(&io);return 90;}
 if(!strcmp(test,"after-mismatch")){u30_verify_set("/private/tmp/no-such-trial-inputs",1);return 90;}
 u30_verify_set(dir,1);assert(u30_wire_allowed(5)&&!u30_wire_allowed(1));
 puts("PASS: frozen pinned payload, exact single target, every chunk, pre/post six hashes and reset gate");return 0;
}
