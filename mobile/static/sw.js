'use strict'
const version = 'xinwen_v1.4'
const offlineResources = [
  '/',
  './static/images/default.png',
  './static/json/offline.json'
]
// 过滤需要加入缓存的api
const addApiCache = [
  /https?:\/\/www.easy-mock.com\//
]
// 需要缓存的请求
const shouldAlwaysFetch = (request) => {
  return true //addApiCache.some(regex => request.url.match(regex))
}
 
/**
 * common function
 */
function cacheKey () {
  return [version, ...arguments].join(':')
}
 
function log () {
  console.log('SW:', ...arguments)
}
 
// 缓存 html 页面
function shouldFetchAndCache (request) {
  return (/text\/html/i).test(request.headers.get('Accept'))
}
/**
 * onClickNotify
 */
 
function onClickNotify (event) {
  var action = event.action
  console.log(`action tag: ${event.notification.tag}`, `action: ${action}`)
 
  switch (action) {
    case 'show-book':
      console.log('show-book')
      break
    case 'contact-me':
      console.log('contact-me')
      break
    default:
      console.log(`未处理的action: ${event.action}`)
      action = 'default'
      break
  }
  event.notification.close()
 
  event.waitUntil(
    // event.waitUntil(async function() {
    // 获取所有clients
    self.clients.matchAll().then(function (clients) {
      // debugger
      if (!clients || clients.length === 0) {
        return
      }
      clients.forEach(function (client) {
        // 使用postMessage进行通信
        client.postMessage(action)
      })
    })
  )
 
}
 
/**
 * Install 安装
 */
 
function onInstall (event) {
  log('install event in progress.')
  event.waitUntil(
    caches.open(cacheKey('offline'))
      .then(cache => cache.addAll(offlineResources))
      .then(() => log('installation complete! version: ' + version))
      .then(() => self.skipWaiting())
  )
}
 
/**
 * Fetch
 */
 
// 当网络离线或请求发生了错误，使用离线资源替代 request 请求
function offlineResponse (request) {
  // debugger
  log('(offline)', request.method, request.url)
  if (request.url.match(/\.(jpg|png|gif|svg|jpeg)(\?.*)?$/)) {
    return caches.match('/static/images/default.png')
  } else {
    // return caches.match('/offline.html')
    return caches.match('./static/json/offline.json')
  }
}
 
// 从网络请求，并将请求成功的资源缓存
function networkedAndCache (request) {
  return fetch(request)
    .then(response => {
      const copy = response.clone()
 
      caches.open(cacheKey('resources'))
        .then(cache => {
          cache.put(request, copy)
        })
      log('(network: cache write)', request.method, request.url)
      return response
    })
}
 
// 优先从 cache 读取，读取失败则从网络请求并缓存。网络请求也失败，则使用离线资源替代
function cachedOrNetworked (request) {
  return caches.match(request)
    .then((response) => {
      log(response ? '(cached)' : '(network: cache miss)', request.method, request.url)
      return response ||
        networkedAndCache(request)
          .catch(() => offlineResponse(request))
    })
}
// 离线断网读取缓存：优先从 cache 读取，读取失败则使用离线资源替代
function cachedOroffline (request) {
  return caches.match(request)
    .then((response) => {
      // debugger
      log(response ? '(cached)' : '(network: cache miss)', request.method, request.url)
      return response || offlineResponse(request)
    })
  // .catch(() => offlineResponse(request))
}
// 优先从网络请求，请求成功则加入缓存，请求失败则用缓存，再失败则使用离线资源替代
function networkedOrcachedOrOffline (request) {
  return fetch(request)
    .then(response => {
      const copy = response.clone()
      caches.open(cacheKey('resources'))
        .then(cache => {
          cache.put(request, copy)
        })
      log('(network)', request.method, request.url)
      return response
    })
    .catch(() => cachedOroffline(request))
}
 
function onFetch (event) {
  const request = event.request
  // 优先从网络请求，请求失败则用缓存，再失败则使用离线资源替代
  log(shouldAlwaysFetch(request))
  if (shouldAlwaysFetch(request)) {
    log('AlwaysFetch request: ', event.request.url)
    event.respondWith(networkedOrcachedOrOffline(request))
    return
  }
  // 应当从网络请求并缓存的资源
  // 如果请求失败，则尝试从缓存读取，读取失败则使用离线资源替代
  // // debugger
  log(shouldFetchAndCache(request))
  if (shouldFetchAndCache(request)) {
    event.respondWith(
      networkedAndCache(request).catch(() => cachedOrOffline(request))
    )
    return
  }
  // 优先从 cache 读取，读取失败则从网络请求并缓存。网络请求也失败，则使用离线资源替代
  event.respondWith(cachedOrNetworked(request))
}
 
/**
 * Activate
 */
function removeOldCache () {
  return caches
    .keys()
    .then(keys =>
      Promise.all( // 等待所有旧的资源都清理完成
        keys
          .filter(key => !key.startsWith(version)) // 过滤不需要删除的资源
          .map(key => caches.delete(key)) // 删除旧版本资源，返回为 Promise 对象
      )
    )
    .then(() => {
      log('removeOldCache completed.')
    })
}
 
function onActivate (event) {
  log('activate event in progress.')
  event.waitUntil(Promise.all([
    // 更新客户端
    self.clients.claim(),
    removeOldCache()
  ]))
}
 
log('Hello from ServiceWorker land!', version)
self.addEventListener('install', onInstall)
self.addEventListener('fetch', onFetch)
self.addEventListener('activate', onActivate)
// self.addEventListener('push', onPush)
// self.addEventListener('sync', onSync)
// self.addEventListener('message', onMessage)
// self.addEventListener('offline', offline)
self.addEventListener('notificationclick', onClickNotify)