import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./pages/home').then((m) => m.Home) },
  { path: 'join/:code', loadComponent: () => import('./pages/home').then((m) => m.Home) },
  { path: 'pay/:code', loadComponent: () => import('./pages/pay').then((m) => m.Pay) },
  { path: 'bank/:code', loadComponent: () => import('./pages/bank').then((m) => m.Bank) },
  { path: 'game/:code', loadComponent: () => import('./pages/game').then((m) => m.Game) },
  { path: '**', redirectTo: '' },
];
