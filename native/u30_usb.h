#pragma once
#include <libusb.h>
int u30_open_target(int pid, unsigned timeout_ms, libusb_device_handle **handle);
int u30_wait_removed(libusb_device_handle *handle, unsigned timeout_ms);
