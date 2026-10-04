#include "u30_guard.h"
#include <sys/stat.h>
#include PROFILE_HEADER
static int verified;
static int directory_ok(const char *s){
 if(!s||s[0]!='/'||strlen(s)>300||strstr(s,".."))return 0;
 for(;*s;s++)if(!isalnum((unsigned char)*s)&&*s!='/'&&*s!='_'&&*s!='-'&&*s!='.')return 0;
 return 1;
}
int u30_wire_allowed(int t){
 if(t==5)return verified;
 switch(t){case 0:case 4:case 0x0d:case 0x10:case 0x11:case 0x12:case 0x13:case 0x21:case 0x2d:case 0x7e:return 1;default:return 0;}
}
int u30_command_arity(int count,char **a,int synthetic,int fdl1,int fdl2){
 if(count<1)return 0;
 if(!strcmp(a[0],"loadfdl"))return synthetic&&count==2&&fdl1==-1&&fdl2==-1&&!strcmp(a[1],"0x0")?2:0;
 if(!strcmp(a[0],"exec")||!strcmp(a[0],"reset")||!strcmp(a[0],"verify_after"))return 1;
 if(!strcmp(a[0],"verbose"))return count>=2&&!strcmp(a[1],"0")?2:0;
 if(!strcmp(a[0],"path"))return count>=2&&directory_ok(a[1])?2:0;
 if(!strcmp(a[0],"read_part")&&count>=5&&!strcmp(a[2],"0")){
  for(size_t i=0;i<sizeof(read_parts)/sizeof(read_parts[0]);i++){
   char size[32];sprintf(size,"%zu",read_parts[i].size);
   if(!strcmp(a[1],read_parts[i].name)&&!strcmp(a[3],size)&&!strcmp(a[4],read_parts[i].filename))return 5;
  }
 }
 return 0;
}
int u30_validate_cli(int argc,char **argv){
 if(argc==2&&!strcmp(argv[1],"--help"))return 1;
 int i=1;
 #define EXPECT(s) do{if(i>=argc||strcmp(argv[i++],s))return 0;}while(0)
 EXPECT("--wait");EXPECT("300");EXPECT("--verbose");EXPECT("1");EXPECT("--kickto");EXPECT("2");EXPECT("exec");EXPECT("verbose");EXPECT("0");EXPECT("path");
 if(i>=argc||!directory_ok(argv[i++]))return 0;
 for(size_t j=0;j<sizeof(read_parts)/sizeof(read_parts[0]);j++){
  char size[32];sprintf(size,"%zu",read_parts[j].size);
  EXPECT("read_part");EXPECT(read_parts[j].name);EXPECT("0");EXPECT(size);EXPECT(read_parts[j].filename);
 }
 EXPECT("verify_after");EXPECT("reset");return i==argc;
 #undef EXPECT
}
void u30_verify_set(const char *dir,int after){
 if(!directory_ok(dir)||!after||verified)ERR_EXIT("READ_POLICY: invalid verification phase\n");
 for(size_t i=0;i<sizeof(read_parts)/sizeof(read_parts[0]);i++){
  char path[512];struct stat st;snprintf(path,sizeof(path),"%s/%s",dir,read_parts[i].filename);
  if(lstat(path,&st)||!S_ISREG(st.st_mode)||st.st_size!=(off_t)read_parts[i].size)
   ERR_EXIT("READ_POLICY: incomplete or invalid output; no reset\n");
 }
 verified=1;DBG_LOG("READ_VERIFIED_AFTER\n");
}
void u30_perform_write(spdio_t *io){(void)io;ERR_EXIT("READ_POLICY: writes unavailable\n");}
