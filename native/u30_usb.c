#include "u30_usb.h"
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static uint64_t monotonic_ms(void) {
 struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))abort();
 return (uint64_t)t.tv_sec*1000+(uint64_t)t.tv_nsec/1000000;
}
static int target(uint8_t *bus,uint8_t *ports,int *depth) {
 const char *b=getenv("U30_USB_BUS"),*p=getenv("U30_USB_PORTS");char *end;unsigned long n;
 if(!b||!p||!*b||!*p)return LIBUSB_ERROR_INVALID_PARAM;
 for(const char *q=b;*q;q++)if(*q<'0'||*q>'9')return LIBUSB_ERROR_INVALID_PARAM;
 n=strtoul(b,&end,10);if(*end||n>255)return LIBUSB_ERROR_INVALID_PARAM;*bus=(uint8_t)n;*depth=0;
 while(*p){if(*depth==8||*p<'0'||*p>'9')return LIBUSB_ERROR_INVALID_PARAM;
  n=strtoul(p,&end,10);if(n<1||n>255||(*end&&*end!='.'))return LIBUSB_ERROR_INVALID_PARAM;
  ports[(*depth)++]=(uint8_t)n;if(!*end)break;p=end+1;if(!*p)return LIBUSB_ERROR_INVALID_PARAM;
 }
 return 0;
}
int u30_open_target(int pid,unsigned timeout_ms,libusb_device_handle **out) {
 uint8_t bus,wanted[8];int depth,error=target(&bus,wanted,&depth);*out=NULL;
 if(error)return error;if(pid!=0&&pid!=0x4d00&&pid!=0x4d03)return LIBUSB_ERROR_INVALID_PARAM;
 uint64_t deadline=monotonic_ms()+timeout_ms;
 for(;;){libusb_device **devices=NULL,*selected=NULL;int count=0;ssize_t n=libusb_get_device_list(NULL,&devices);
  if(n<0)return (int)n;
  for(ssize_t i=0;i<n;i++){struct libusb_device_descriptor d;uint8_t path[8];
   if(libusb_get_device_descriptor(devices[i],&d)||d.idVendor!=0x1782)continue;
   if(pid ? d.idProduct!=pid : (d.idProduct!=0x4d00&&d.idProduct!=0x4d03))continue;
   if(libusb_get_bus_number(devices[i])!=bus||libusb_get_port_numbers(devices[i],path,8)!=depth||memcmp(path,wanted,(size_t)depth))continue;
   selected=devices[i];count++;
  }
  if(count>1){libusb_free_device_list(devices,1);return LIBUSB_ERROR_BUSY;}
  if(count==1){error=libusb_open(selected,out);libusb_free_device_list(devices,1);
   if(error!=LIBUSB_ERROR_NO_DEVICE&&error!=LIBUSB_ERROR_NOT_FOUND)return error;
   *out=NULL;
  }else libusb_free_device_list(devices,1);
  if(monotonic_ms()>=deadline)return LIBUSB_ERROR_TIMEOUT;
  usleep(100000);
 }
}
int u30_wait_removed(libusb_device_handle *handle,unsigned timeout_ms) {
 if(!handle)return LIBUSB_ERROR_INVALID_PARAM;
 libusb_device *old=libusb_get_device(handle);uint64_t deadline=monotonic_ms()+timeout_ms;
 for(;;){libusb_device **devices=NULL;ssize_t n=libusb_get_device_list(NULL,&devices);int present=0;
  if(n<0)return (int)n;
  for(ssize_t i=0;i<n;i++)if(devices[i]==old)present=1;
  libusb_free_device_list(devices,1);
  if(!present)return 0;
  if(monotonic_ms()>=deadline)return LIBUSB_ERROR_TIMEOUT;
  usleep(100000);
 }
}
