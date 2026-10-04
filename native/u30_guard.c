#include "u30_guard.h"
#include <CommonCrypto/CommonDigest.h>
#include PROFILE_HEADER
static unsigned char *frozen_candidate;
static int phase,write_window;
static int hash_file(const char *path,size_t size,const char *expected,unsigned char **frozen){
 FILE *f=fopen(path,"rb");if(!f)return 0;unsigned char *buf=malloc(size);if(!buf){fclose(f);return 0;}
 size_t n=fread(buf,1,size,f);int extra=fgetc(f),failed=ferror(f);fclose(f);
 unsigned char digest[CC_SHA256_DIGEST_LENGTH];char hex[65];CC_SHA256(buf,(CC_LONG)n,digest);
 for(int i=0;i<32;i++)sprintf(hex+2*i,"%02x",digest[i]);hex[64]=0;
 int ok=n==size&&extra==EOF&&!failed&&!strcmp(hex,expected);
 if(ok&&frozen)*frozen=buf;else free(buf);return ok;
}
static int safe_directory(const char *s){if(!s||s[0]!='/'||strlen(s)>300||strstr(s,".."))return 0;for(;*s;s++)if(!isalnum((unsigned char)*s)&&*s!='/'&&*s!='_'&&*s!='-'&&*s!='.')return 0;return 1;}
int u30_wire_allowed(int t){
 if(t==1||t==2||t==3)return write_window&&phase==1;
 if(t==5)return phase==3;
 switch(t){case 0:case 4:case 0x0d:case 0x10:case 0x11:case 0x12:case 0x13:case 0x21:case 0x2d:case 0x7e:return 1;default:return 0;}
}
int u30_command_arity(int count,char **a,int synthetic,int fdl1,int fdl2){
 if(count<1)return 0;
 if(!strcmp(a[0],"loadfdl"))return synthetic&&count==2&&fdl1==-1&&fdl2==-1&&!strcmp(a[1],"0x0")?2:0;
 if(!strcmp(a[0],"exec")||!strcmp(a[0],"reset")||!strcmp(a[0],"verify_before")||!strcmp(a[0],"verify_after")||!strcmp(a[0],"write_pinned"))return 1;
 if(!strcmp(a[0],"verbose"))return count>=2&&!strcmp(a[1],"0")?2:0;
 if(!strcmp(a[0],"path"))return count>=2&&safe_directory(a[1])?2:0;
 if(!strcmp(a[0],"read_part")&&count>=5&&!strcmp(a[2],"0")){
  for(unsigned i=0;i<6;i++){char size[32],pre[80],post[80];sprintf(size,"%zu",pinned_parts[i].size);sprintf(pre,"pre-%s.bin",pinned_parts[i].name);sprintf(post,"post-%s.bin",pinned_parts[i].name);
   if(!strcmp(a[1],pinned_parts[i].name)&&!strcmp(a[3],size)&&(!strcmp(a[4],pre)||!strcmp(a[4],post)))return 5;
  }
 }
 return 0;
}
int u30_validate_cli(int argc,char **argv){
 if(argc==2&&!strcmp(argv[1],"--help"))return 1;
 int i=1;
 #define EXPECT(s) do{if(i>=argc||strcmp(argv[i++],s))return 0;}while(0)
 EXPECT("--wait");EXPECT("300");EXPECT("--verbose");EXPECT("1");EXPECT("--kickto");EXPECT("2");EXPECT("exec");EXPECT("verbose");EXPECT("0");EXPECT("path");if(i>=argc||!safe_directory(argv[i++]))return 0;
 for(int after=0;after<2;after++){
  for(int j=0;j<6;j++){char size[32],filename[80];sprintf(size,"%zu",pinned_parts[j].size);sprintf(filename,"%s-%s.bin",after?"post":"pre",pinned_parts[j].name);
   EXPECT("read_part");EXPECT(pinned_parts[j].name);EXPECT("0");EXPECT(size);EXPECT(filename);
  }
  if(!after){EXPECT("verify_before");EXPECT("write_pinned");}else EXPECT("verify_after");
 }
 EXPECT("reset");if(i!=argc)return 0;
 #undef EXPECT
 if(frozen_candidate)return 0;
 return hash_file(candidate_path,candidate_size,candidate_hash,&frozen_candidate);
}
void u30_verify_set(const char *dir,int after){
 if(!safe_directory(dir)||phase!=(after?2:0))ERR_EXIT("TRIAL_POLICY: invalid verify phase\n");
 for(int i=0;i<6;i++){char path[512];snprintf(path,sizeof(path),"%s/%s-%s.bin",dir,after?"post":"pre",pinned_parts[i].name);
  if(!hash_file(path,pinned_parts[i].size,after?pinned_parts[i].after:pinned_parts[i].before,NULL))ERR_EXIT("TRIAL_POLICY: %s %s hash mismatch; no write/reset follows\n",after?"after":"before",pinned_parts[i].name);
 }
 phase=after?3:1;DBG_LOG("TRIAL_VERIFIED_%s\n",after?"AFTER":"BEFORE");
}
/* Explicit single-partition path; never calls generic write/unify/NV/repartition. */
void u30_perform_write(spdio_t *io){
 extern int selected_ab;
 if((strcmp(write_target,"init_boot_b")&&strcmp(write_target,"trustos_b"))||phase!=1||!frozen_candidate||selected_ab!=2)ERR_EXIT("TRIAL_POLICY: write prerequisites failed\n");
 int found=0;for(int i=0;i<io->part_count;i++)if(!strcmp(io->ptable[i].name,write_target)&&io->ptable[i].size==(long long)candidate_size)found++;
 if(found!=1)ERR_EXIT("TRIAL_POLICY: target partition identity/size mismatch\n");
 memset(io->temp_buf,0,76);for(size_t i=0;i<strlen(write_target);i++)io->temp_buf[2*i]=(unsigned char)write_target[i];for(int j=0;j<4;j++)io->temp_buf[72+j]=(unsigned char)(candidate_size>>(8*j));
 int oldtimeout=io->timeout;io->timeout=15000;
 write_window=1;encode_msg_nocpy(io,1,76);if(send_and_check(io))ERR_EXIT("TRIAL_WRITE_START_FAILED; no reset\n");
 size_t offset=0;
 while(offset<candidate_size){size_t n=candidate_size-offset;if(n>0xf800)n=0xf800;memcpy(io->temp_buf,frozen_candidate+offset,n);encode_msg_nocpy(io,2,n);
  if(send_and_check(io))ERR_EXIT("TRIAL_WRITE_DATA_FAILED at %zu; no reset\n",offset);offset+=n;
 }
 encode_msg_nocpy(io,3,0);if(send_and_check(io))ERR_EXIT("TRIAL_WRITE_END_FAILED; no reset\n");
 write_window=0;phase=2;io->timeout=oldtimeout;free(frozen_candidate);frozen_candidate=NULL;
 DBG_LOG("TRIAL_WRITE_ACKED %s %zu; readback still required\n",write_target,offset);
}
