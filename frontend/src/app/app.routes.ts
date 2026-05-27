import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./pages/home/home.component').then(m => m.HomeComponent) },
  { path: 'builds/:id', loadComponent: () => import('./pages/build/build.component').then(m => m.BuildComponent) },
  { path: 'builds/:id/explore', loadComponent: () => import('./pages/explore/explore.component').then(m => m.ExploreComponent) },
  { path: '**', redirectTo: '' },
];
