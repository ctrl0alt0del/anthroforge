#pragma once
#ifdef _WIN32
#define AF_NATIVE_EXPORT extern "C" __declspec(dllexport)
#else
#define AF_NATIVE_EXPORT extern "C" __attribute__((visibility("default")))
#endif
